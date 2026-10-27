"""Chat service (CODEWRIGHT.md Sections 2.2 and 3): one reply per user message, streamed.

A turn: route the message (slash command, language rule, model) → decline / ask / answer (tier 0) or run the
missing-info check → questions → confirm card. Nothing is made until the user presses Start (Section 3.4). Start runs
the intent's playbook when it exists, shown as a run card; a finished run gets a Done card.

Messages form a tree: editing a message or regenerating a reply adds a sibling, and `Conversation.head_id` is the
leaf of the branch on screen. Live updates go over the shared event bus on the key `chat:<conversation id>`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from agent.chat import intake, router
from agent.chat.answer import stream_answer
from agent.chat.intents import INTENT_LABELS, PLAYBOOK_PHASE, intent_config, named_language
from agent.llm.client import LLMClient, LLMError, LLMUnavailable
from agent.llm.client import Message as LLMMessage
from agent.llm.structured import StructuredOutputError
from agent.playbooks.registry import playbooks
from codewright_api.db import Conversation, MemoryItem, Message, Run
from codewright_api.runs import RunConflict, RunManager
from codewright_api.tracing import PostgresTraceSink

log = logging.getLogger(__name__)

YES = re.compile(r"^\s*(yes|yep|yeah|y|ok|okay|sure|start|go|go ahead|do it|looks good|lgtm)\b[\s.!]*$", re.I)
TITLE_CHARS = 60


class ChatBusy(Exception):
    """A reply is still being written in this conversation."""


def message_dict(m: Message, siblings: list[uuid.UUID] | None = None) -> dict[str, Any]:
    sibs = siblings or [m.id]
    return {
        "id": str(m.id),
        "conversation_id": str(m.conversation_id),
        "parent_id": str(m.parent_id) if m.parent_id else None,
        "role": m.role,
        "kind": m.kind,
        "content": m.content,
        "data": m.data,
        "status": m.status,
        "run_id": str(m.run_id) if m.run_id else None,
        "created_at": m.created_at.isoformat() if m.created_at else datetime.now(UTC).isoformat(),
        "siblings": [str(s) for s in sibs],
    }


def _title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def _questions_markdown(questions: list[intake.Question]) -> str:
    lines = ["Before I start, a few quick questions:"]
    for i, q in enumerate(questions, 1):
        options = f" {' · '.join(q.options)}" if q.options else ""
        why = f": {q.hint}" if q.hint else ""
        lines.append(f"{i}. **{q.question}**{options} *(default: {q.default}{why})*")
    lines.append("\nAnswer in one message, or say “defaults are fine”.")
    return "\n".join(lines)


def _card_markdown(card: intake.ConfirmCard) -> str:
    features = "\n".join(f"- {f}" for f in card.features)
    return (
        f"**Here's what I'll make:** {card.what}\n\n**Stack:** {card.stack}\n\n{features}\n\n"
        f"**You get:** {card.deliver}"
    )


class ChatService:
    def __init__(self, manager: RunManager) -> None:
        self.manager = manager
        self.sessions = manager.sessions
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        manager.status_listeners.append(self._on_run_status)

    # ── bus ──────────────────────────────────────────────────────────────────
    @staticmethod
    def key(conversation_id: uuid.UUID) -> str:
        return f"chat:{conversation_id}"

    def _publish(self, conversation_id: uuid.UUID, event: dict[str, Any]) -> None:
        self.manager.bus.publish(self.key(conversation_id), event)

    def busy(self, conversation_id: uuid.UUID) -> bool:
        task = self._tasks.get(conversation_id)
        return task is not None and not task.done()

    async def stop_all(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # ── reading ──────────────────────────────────────────────────────────────
    async def thread(self, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
        """The messages of the branch on screen, root first, each with its siblings (for < 2/3 > switching)."""
        async with self.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                raise LookupError(conversation_id)
            rows = list(
                await session.scalars(
                    select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
                )
            )
        by_id = {m.id: m for m in rows}
        children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for m in rows:
            children.setdefault(m.parent_id, []).append(m.id)
        path: list[Message] = []
        node = by_id.get(conv.head_id) if conv.head_id else None
        while node is not None:
            path.append(node)
            node = by_id.get(node.parent_id) if node.parent_id else None
        return [message_dict(m, children.get(m.parent_id)) for m in reversed(path)]

    async def _history(self, session: Any, leaf_id: uuid.UUID | None) -> list[Message]:
        """Messages from the root to `leaf_id`, inclusive."""
        path: list[Message] = []
        node_id = leaf_id
        while node_id is not None:
            node = await session.get(Message, node_id)
            if node is None:
                break
            path.append(node)
            node_id = node.parent_id
        return list(reversed(path))

    # ── commands ─────────────────────────────────────────────────────────────
    async def send(
        self,
        conversation_id: uuid.UUID | None,
        text: str,
        *,
        parent_id: uuid.UUID | None = None,
        use_parent: bool = False,
        project_id: uuid.UUID | None = None,
    ) -> tuple[Conversation, dict[str, Any], dict[str, Any]]:
        """Add a user message (after the head, or after `parent_id` when editing) and start the reply."""
        text = text.strip()
        if not text:
            raise ValueError("The message is empty.")
        async with self.sessions() as session:
            if conversation_id is None:
                conv = Conversation(title=_title(re.sub(r"^/\S+\s*", "", text) or text), project_id=project_id)
                session.add(conv)
                await session.flush()
            else:
                found = await session.get(Conversation, conversation_id)
                if found is None:
                    raise LookupError(conversation_id)
                conv = found
                if self.busy(conv.id):
                    raise ChatBusy("Codewright is still replying. Stop it first or wait.")
            user = Message(
                conversation_id=conv.id,
                parent_id=parent_id if use_parent else conv.head_id,
                role="user",
                content=text,
            )
            session.add(user)
            await session.flush()
            reply = Message(conversation_id=conv.id, parent_id=user.id, role="assistant", status="streaming")
            session.add(reply)
            await session.flush()
            conv.head_id = reply.id
            conv.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(user)
            await session.refresh(reply)
            await session.refresh(conv)
        self._start(conv.id, reply.id)
        return conv, message_dict(user), message_dict(reply)

    async def regenerate(self, conversation_id: uuid.UUID, message_id: uuid.UUID) -> dict[str, Any]:
        """A new reply to the same user message, as a sibling of `message_id`."""
        if self.busy(conversation_id):
            raise ChatBusy("Codewright is still replying. Stop it first or wait.")
        async with self.sessions() as session:
            old = await session.get(Message, message_id)
            if old is None or old.conversation_id != conversation_id or old.role != "assistant":
                raise LookupError(message_id)
            reply = Message(
                conversation_id=conversation_id, parent_id=old.parent_id, role="assistant", status="streaming"
            )
            session.add(reply)
            await session.flush()
            await session.execute(
                update(Conversation).where(Conversation.id == conversation_id).values(head_id=reply.id)
            )
            await session.commit()
            await session.refresh(reply)
        self._start(conversation_id, reply.id)
        return message_dict(reply)

    async def switch(self, conversation_id: uuid.UUID, message_id: uuid.UUID) -> None:
        """Show the branch through `message_id` (its latest leaf)."""
        async with self.sessions() as session:
            node = await session.get(Message, message_id)
            if node is None or node.conversation_id != conversation_id:
                raise LookupError(message_id)
            while True:
                child = await session.scalar(
                    select(Message.id).where(Message.parent_id == node.id).order_by(Message.created_at.desc()).limit(1)
                )
                if child is None:
                    break
                node = await session.get(Message, child)
                if node is None:
                    raise LookupError(child)
            await session.execute(
                update(Conversation).where(Conversation.id == conversation_id).values(head_id=node.id)
            )
            await session.commit()

    async def stop(self, conversation_id: uuid.UUID) -> None:
        """Stop the reply being written (the text so far is kept) and any run this chat started."""
        task = self._tasks.pop(conversation_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.sessions() as session:
            runs = list(
                await session.scalars(
                    select(Run.id).where(
                        Run.conversation_id == conversation_id, Run.status.in_(("created", "running", "waiting"))
                    )
                )
            )
        for run_id in runs:
            await self.manager.cancel(run_id)

    async def confirm(self, conversation_id: uuid.UUID, message_id: uuid.UUID, choice: str) -> dict[str, Any] | None:
        """[Start] or [Change something] on a confirm card."""
        async with self.sessions() as session:
            card = await session.get(Message, message_id)
            if card is None or card.conversation_id != conversation_id or card.kind != "confirm":
                raise LookupError(message_id)
            if card.data.get("state") != "open":
                raise RunConflict("This card was already answered.")
            card.data = {**card.data, "state": "started" if choice == "start" else "changing"}
            await session.commit()
            await session.refresh(card)
        self._publish(conversation_id, {"type": "message", "message": message_dict(card)})
        if choice != "start":
            return None
        return await self._start_work(conversation_id, card)

    # ── the reply ────────────────────────────────────────────────────────────
    def _start(self, conversation_id: uuid.UUID, reply_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._respond(conversation_id, reply_id), name=f"chat-{conversation_id}")
        self._tasks[conversation_id] = task
        task.add_done_callback(
            lambda t: self._tasks.pop(conversation_id, None) if self._tasks.get(conversation_id) is t else None
        )

    def _client(self, role: str) -> LLMClient:
        llm = self.manager.llm
        tracer = PostgresTraceSink(self.sessions, run_id=None, step="chat", role=role)
        return llm.client(llm.active_profile, tracer)

    async def _finish(self, reply_id: uuid.UUID, **values: Any) -> None:
        async with self.sessions() as session:
            reply = await session.get(Message, reply_id)
            if reply is None:
                return
            for k, v in {"status": "complete", **values}.items():
                setattr(reply, k, v)
            await session.commit()
            await session.refresh(reply)
        self._publish(reply.conversation_id, {"type": "message", "message": message_dict(reply)})

    async def _respond(self, conversation_id: uuid.UUID, reply_id: uuid.UUID) -> None:
        text_so_far: list[str] = []
        try:
            await self._turn(conversation_id, reply_id, text_so_far)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await asyncio.shield(self._finish(reply_id, content="".join(text_so_far), status="stopped"))
            raise
        except LLMUnavailable as exc:
            await self._finish(
                reply_id,
                kind="error",
                status="error",
                content=f"The model server isn't reachable right now ({exc}). Check it in Settings, then retry.",
            )
        except (LLMError, StructuredOutputError) as exc:
            log.warning("chat reply failed: %s", exc)
            await self._finish(reply_id, kind="error", status="error", content=f"Something went wrong: {exc}")
        except Exception as exc:
            log.exception("chat reply failed")
            await self._finish(reply_id, kind="error", status="error", content=f"Something went wrong: {exc}")

    async def _turn(self, conversation_id: uuid.UUID, reply_id: uuid.UUID, text_so_far: list[str]) -> None:
        async with self.sessions() as session:
            reply = await session.get(Message, reply_id)
            conv = await session.get(Conversation, conversation_id)
            if reply is None or conv is None or reply.parent_id is None:
                raise LookupError(reply_id)
            path = await self._history(session, reply.parent_id)
            prefs = list(
                await session.scalars(
                    select(MemoryItem).where(
                        (MemoryItem.project_id == conv.project_id) | MemoryItem.project_id.is_(None)
                    )
                )
            )
        user = path[-1]
        before = path[:-1]
        previous = before[-1] if before else None
        history: list[LLMMessage] = [
            {"role": m.role, "content": m.content} for m in before if m.content and m.kind != "error"
        ]
        preferences = [f"{p.key}: {p.value}" for p in prefs]
        has_project = conv.project_id is not None

        # A reply to open questions, or a typed answer to an open confirm card, continues the intake.
        if previous is not None and previous.kind == "questions":
            await self._intake_round(reply_id, previous.data, user.content, preferences)
            return
        if previous is not None and previous.kind == "confirm" and previous.data.get("state") in ("open", "changing"):
            if YES.match(user.content) and previous.data.get("state") == "open":
                await self._finish(reply_id, content="Starting.", kind="text")
                await self.confirm(conversation_id, previous.id, "start")
                return
            await self._close_card(previous.id, "changed")
            data = {**previous.data, "answers": [*previous.data.get("answers", []), ["Change requested", user.content]]}
            await self._intake_round(reply_id, data, None, preferences, force_card=True)
            return

        route = await router.route(self._client("router"), user.content, history=history, has_project=has_project)
        meta = {"intent": route.intent, "tier": route.tier, "confidence": route.confidence, "command": route.command}
        if route.decline:
            await self._finish(reply_id, kind="decline", content=route.decline, data=meta)
            return
        if route.question:
            await self._finish(reply_id, content=route.question, data=meta)
            return
        if route.intent is None:  # only declines have no intent
            raise LLMError("The router returned no intent.")
        if route.tier == 0:
            await self._stream(
                reply_id, history, route.args or user.content, route.intent, has_project, meta, text_so_far
            )
            return
        request = route.args if route.command and route.args else user.content
        state = {**meta, "request": request, "targets": route.targets, "answers": [], "round": 0}
        await self._intake_round(reply_id, state, None, preferences)

    async def _stream(
        self,
        reply_id: uuid.UUID,
        history: list[LLMMessage],
        question: str,
        intent: str,
        has_project: bool,
        meta: dict[str, Any],
        text_so_far: list[str],
    ) -> None:
        async with self.sessions() as session:
            reply = await session.get(Message, reply_id)
            if reply is None:
                raise LookupError(reply_id)
            reply.data = meta
            conversation_id = reply.conversation_id
            await session.commit()
        async for token in stream_answer(
            self._client("project_manager"), history, question, intent=intent, has_project=has_project
        ):
            text_so_far.append(token)
            self._publish(conversation_id, {"type": "token", "message_id": str(reply_id), "text": token})
        await self._finish(reply_id, content="".join(text_so_far))

    async def _intake_round(
        self,
        reply_id: uuid.UUID,
        state: dict[str, Any],
        answer: str | None,
        preferences: list[str],
        *,
        force_card: bool = False,
    ) -> None:
        answers = [tuple(a) for a in state.get("answers", [])]
        if answer is not None:
            answers.append((" / ".join(q["question"] for q in state.get("questions", [])), answer))
        round_no = 2 if force_card else int(state.get("round", 0)) + 1
        result = await intake.check(
            self._client("clarifier"),
            state["intent"],
            state["request"],
            answers=answers,
            preferences=preferences,
            round_no=round_no,
        )
        if result.language and named_language(" ".join(a for _, a in answers)):
            await self._remember("preferred language", result.language)
        data = {
            **{k: v for k, v in state.items() if k != "questions"},
            "answers": [list(a) for a in answers],
            "round": round_no,
            "language": result.language,
        }
        if result.questions:
            questions = [q.model_dump() for q in result.questions]
            await self._finish(
                reply_id,
                kind="questions",
                content=_questions_markdown(result.questions),
                data={**data, "questions": questions},
            )
            return
        card = result.card.model_dump()
        await self._finish(
            reply_id,
            kind="confirm",
            content=_card_markdown(result.card),
            data={**data, "card": card, "state": "open", "label": INTENT_LABELS[state["intent"]]},
        )

    async def _close_card(self, message_id: uuid.UUID, state: str) -> None:
        async with self.sessions() as session:
            card = await session.get(Message, message_id)
            if card is None:
                return
            card.data = {**card.data, "state": state}
            await session.commit()
            await session.refresh(card)
        self._publish(card.conversation_id, {"type": "message", "message": message_dict(card)})

    async def _remember(self, key: str, value: str) -> None:
        async with self.sessions() as session:
            row = await session.scalar(select(MemoryItem).where(MemoryItem.project_id.is_(None), MemoryItem.key == key))
            if row is None:
                session.add(MemoryItem(project_id=None, key=key, value=value))
            else:
                row.value = value
            await session.commit()

    # ── after Start ──────────────────────────────────────────────────────────
    async def _append(self, conversation_id: uuid.UUID, **values: Any) -> dict[str, Any]:
        """Add an assistant message after the current head and make it the head."""
        async with self.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                raise LookupError(conversation_id)
            msg = Message(conversation_id=conversation_id, parent_id=conv.head_id, role="assistant", **values)
            session.add(msg)
            await session.flush()
            conv.head_id = msg.id
            conv.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(msg)
        out = message_dict(msg)
        self._publish(conversation_id, {"type": "message", "message": out})
        return out

    async def _start_work(self, conversation_id: uuid.UUID, card: Message) -> dict[str, Any]:
        intent = card.data["intent"]
        cfg = intent_config(intent)
        inputs = _run_inputs(intent, card.data)
        if cfg.playbook not in playbooks() or inputs is None:
            return await self._append(
                conversation_id,
                content=(
                    f"Confirmed. The **{INTENT_LABELS[intent]}** playbook is built in Phase {PLAYBOOK_PHASE[intent]}, "
                    "so I can't make this yet. Your request, answers and this plan are saved in this chat. Meanwhile "
                    "I can answer questions about it."
                ),
                data={"intent": intent, "pending_phase": PLAYBOOK_PHASE[intent]},
            )
        async with self.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                raise LookupError(conversation_id)
        try:
            run = await self.manager.create_run(
                playbook=cfg.playbook,
                inputs=inputs,
                tier=int(card.data.get("tier") or 0),
                conversation_id=conversation_id,
            )
        except RunConflict as exc:
            return await self._append(conversation_id, kind="error", status="error", content=str(exc))
        return await self._append(
            conversation_id, kind="run", run_id=run.id, content="", data={"intent": intent, "playbook": cfg.playbook}
        )

    async def _on_run_status(self, run_id: uuid.UUID, status: str) -> None:
        async with self.sessions() as session:
            run = await session.get(Run, run_id)
        if run is None or run.conversation_id is None:
            return
        self._publish(run.conversation_id, {"type": "run", "run_id": str(run_id), "status": status})
        if status == "completed":
            await self._append(run.conversation_id, kind="done", run_id=run_id, **await self._done_card(run))

    async def _done_card(self, run: Run) -> dict[str, Any]:
        state = await self.manager.state_values(run)
        artifacts = [a for a in state.get("artifacts", []) if isinstance(a, dict)]
        title = playbooks()[run.playbook].title if run.playbook in playbooks() else run.playbook
        guide = None
        workspace = state.get("workspace")
        if workspace and (Path(workspace) / "GUIDE.md").is_file():
            guide = (Path(workspace) / "GUIDE.md").read_text(encoding="utf-8")[:20000]
        steps = [s for s in state.get("plan", []) if isinstance(s, dict)]
        summary = f"{title} finished: {sum(1 for s in steps if s.get('status') == 'done')} of {len(steps)} steps done."
        return {
            "content": summary,
            "data": {
                "summary": summary,
                "changed": [a.get("path") for a in artifacts if a.get("path")],
                "artifacts": artifacts,
                "proof": [],  # tests, replay and benchmark results arrive with the Verification engine (Phase 7)
                "delivered": None,  # delivery targets arrive in Phase 3
                "guide": guide,
                "suggestions": _suggestions(run.playbook),
            },
        }


def _run_inputs(intent: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Playbook inputs from the confirmed card, or None when the request needs something not built yet."""
    if intent == "change_architecture":
        text = (data.get("request") or "").lower()
        return {"target": "microservices", "mode": "audit"} if "microservice" in text else None
    return {"request": data.get("request", "")}


def _suggestions(playbook: str) -> list[str]:
    if playbook == "architecture_change":
        return ["Explain the To-Be design", "Run the full conversion", "Deliver the report"]
    return ["Explain what was done", "Review the result", "Deliver it"]
