import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "@/lib/api";

import { DoneCard, QuestionsCard } from "./cards";

function message(data: ChatMessage["data"]): ChatMessage {
  return {
    id: "m1",
    conversation_id: "c1",
    parent_id: null,
    role: "assistant",
    kind: "done",
    content: data.summary ?? "",
    data,
    status: "complete",
    run_id: "r1",
    created_at: "2026-01-01T00:00:00Z",
    siblings: [],
  };
}

describe("DoneCard", () => {
  it("shows a clean pass as a success, with no destructive styling", () => {
    render(<DoneCard message={message({ summary: "Tic Tac Toe finished: 3 of 3 steps done." })} onSend={vi.fn()} />);
    expect(screen.getByText(/finished/)).toBeInTheDocument();
    expect(screen.queryByText(/did not pass/)).not.toBeInTheDocument();
  });

  it("never shows a green checkmark when a step did not pass", () => {
    render(
      <DoneCard
        message={message({
          summary: "Tic Tac Toe finished: 2 of 3 steps done. 1 step(s) did not pass.",
          passed: false,
        })}
        onSend={vi.fn()}
      />,
    );
    const headline = screen.getByText(/finished/);
    // The headline (and its icon container) must be styled destructive, not the default success green.
    expect(headline.closest("p")).toHaveClass("text-destructive");
  });
});

describe("QuestionsCard", () => {
  it("shows a pick-one question as a dropdown with the default chosen and marked, not as buttons", () => {
    const questions = [
      { question: "Which language?", default: "Python", options: ["Python", "Go"], hint: "" },
      { question: "Which platform?", default: "Web", options: ["Web", "Terminal"], hint: "" },
      { question: "Who is it for?", default: "me", options: [], hint: "" },
    ];
    render(<QuestionsCard message={message({ questions })} canAnswer onSend={vi.fn()} />);
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.getByText("Python (Recommended)")).toBeInTheDocument();
    expect(screen.getByText("Web (Recommended)")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Who is it for?" })).toBeInTheDocument();
    // two dropdowns to a row; the free-text question takes the whole row
    expect(screen.getByRole("list")).toHaveClass("sm:grid-cols-2");
    expect(screen.getByText("Who is it for?").closest("li")).toHaveClass("sm:col-span-2");
  });
});
