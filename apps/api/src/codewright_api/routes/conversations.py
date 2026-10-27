"""Conversations and messages (CODEWRIGHT.md Section 2.2): list, search, rename, pin, delete; send, stop, edit,
regenerate, branch; confirm cards; live updates over SSE."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, exists, or_, select

from agent.chat.intents import SLASH_COMMANDS
from codewright_api.chat import ChatBusy, ChatService
from codewright_api.db import Conversation, MemoryItem, Message, SessionDep
from codewright_api.runs import RunConflict

router = APIRouter(tags=["chat"])


def _chat(request: Request) -> ChatService:
    chat: ChatService | None = getattr(request.app.state, "chat", None)
    if chat is None:
        raise HTTPException(503, "Chat is not available (is the database reachable?).")
    return chat


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    pinned: bool
    project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[dict[str, Any]]
    busy: bool


class NewConversation(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    project_id: uuid.UUID | None = None
    attachments: list[uuid.UUID] = Field(default=[], max_length=10)


class SendResult(BaseModel):
    conversation: ConversationOut
    user: dict[str, Any]
    reply: dict[str, Any]


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    edit_of: uuid.UUID | None = Field(
        default=None, description="Edit this user message: the new one becomes a sibling."
    )
    attachments: list[uuid.UUID] = Field(default=[], max_length=10)


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None


class ConfirmChoice(BaseModel):
    choice: Literal["start", "change"]


@router.get("/commands")
async def commands() -> list[dict[str, str]]:
    """Slash commands for the `/` menu (Phase 6 adds custom skills)."""
    return [
        {"command": f"/{name}", "intent": intent, "description": desc}
        for name, (intent, desc) in SLASH_COMMANDS.items()
    ]


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(session: SessionDep, q: str | None = None, limit: int = 100) -> list[Conversation]:
    query = select(Conversation)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Conversation.title.ilike(like),
                exists().where(Message.conversation_id == Conversation.id, Message.content.ilike(like)),
            )
        )
    query = query.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(min(limit, 500))
    return list(await session.scalars(query))


@router.post("/conversations", response_model=SendResult, status_code=201)
async def create_conversation(body: NewConversation, request: Request) -> SendResult:
    conv, user, reply = await _chat(request).send(
        None, body.content, project_id=body.project_id, attachments=body.attachments
    )
    return SendResult(conversation=ConversationOut.model_validate(conv), user=user, reply=reply)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, request: Request, session: SessionDep) -> ConversationDetail:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    chat = _chat(request)
    return ConversationDetail(
        conversation=ConversationOut.model_validate(conv),
        messages=await chat.thread(conversation_id),
        busy=chat.busy(conversation_id),
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def patch_conversation(conversation_id: uuid.UUID, body: ConversationPatch, session: SessionDep) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    if body.title is not None:
        conv.title = body.title.strip()
    if body.pinned is not None:
        conv.pinned = body.pinned
    await session.commit()
    await session.refresh(conv)
    return conv


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, request: Request, session: SessionDep) -> None:
    await _chat(request).stop(conversation_id)
    result = await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await session.commit()
    if not result.rowcount:  # type: ignore[attr-defined]
        raise HTTPException(404, "Conversation not found")


@router.post("/conversations/{conversation_id}/messages", response_model=SendResult, status_code=201)
async def send_message(
    conversation_id: uuid.UUID, body: NewMessage, request: Request, session: SessionDep
) -> SendResult:
    parent_id = None
    if body.edit_of is not None:
        edited = await session.get(Message, body.edit_of)
        if edited is None or edited.conversation_id != conversation_id or edited.role != "user":
            raise HTTPException(404, "Message not found")
        parent_id = edited.parent_id
    try:
        conv, user, reply = await _chat(request).send(
            conversation_id,
            body.content,
            parent_id=parent_id,
            use_parent=body.edit_of is not None,
            attachments=body.attachments,
        )
    except LookupError:
        raise HTTPException(404, "Conversation not found") from None
    except ChatBusy as exc:
        raise HTTPException(409, str(exc)) from None
    return SendResult(conversation=ConversationOut.model_validate(conv), user=user, reply=reply)


@router.post("/conversations/{conversation_id}/messages/{message_id}/regenerate", status_code=201)
async def regenerate(conversation_id: uuid.UUID, message_id: uuid.UUID, request: Request) -> dict[str, Any]:
    try:
        return await _chat(request).regenerate(conversation_id, message_id)
    except LookupError:
        raise HTTPException(404, "Message not found") from None
    except ChatBusy as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/conversations/{conversation_id}/messages/{message_id}/switch", status_code=204)
async def switch_branch(conversation_id: uuid.UUID, message_id: uuid.UUID, request: Request) -> None:
    try:
        await _chat(request).switch(conversation_id, message_id)
    except LookupError:
        raise HTTPException(404, "Message not found") from None


@router.post("/conversations/{conversation_id}/messages/{message_id}/confirm")
async def confirm(
    conversation_id: uuid.UUID, message_id: uuid.UUID, body: ConfirmChoice, request: Request
) -> dict[str, Any] | None:
    try:
        return await _chat(request).confirm(conversation_id, message_id, body.choice)
    except LookupError:
        raise HTTPException(404, "Message not found") from None
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/conversations/{conversation_id}/stop", status_code=204)
async def stop(conversation_id: uuid.UUID, request: Request) -> None:
    await _chat(request).stop(conversation_id)


@router.get("/conversations/{conversation_id}/events", response_class=EventSourceResponse)
async def conversation_events(conversation_id: uuid.UUID, request: Request) -> AsyncIterator[ServerSentEvent]:
    """Live updates: `token` (a piece of a streamed reply), `message` (a message was added or changed) and `run`
    (a run started from this chat changed status). The client reloads the thread on reconnect."""
    chat = _chat(request)
    key = chat.key(conversation_id)
    queue = chat.manager.bus.subscribe(key)
    try:
        # Sent at once: the client knows it is connected and loads the thread (it subscribed first, so nothing is lost).
        yield ServerSentEvent(event="ready", data={})
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
            except TimeoutError:
                continue
            yield ServerSentEvent(event=event["type"], data=event)
    finally:
        chat.manager.bus.unsubscribe(key, queue)


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: uuid.UUID | None
    key: str
    value: str
    source: str
    updated_at: datetime


@router.get("/memory", response_model=list[MemoryOut])
async def list_memory(session: SessionDep) -> list[MemoryItem]:
    return list(await session.scalars(select(MemoryItem).order_by(MemoryItem.updated_at.desc())))


@router.delete("/memory/{item_id}", status_code=204)
async def delete_memory(item_id: int, session: SessionDep) -> None:
    await session.execute(delete(MemoryItem).where(MemoryItem.id == item_id))
    await session.commit()
