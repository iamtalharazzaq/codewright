import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BudgetPrompt, GatePrompt, LLMUnavailablePrompt } from "@/lib/api";

import { BudgetCard, GateCard, LLMUnavailableCard } from "./pending-card";

const gate: GatePrompt = {
  kind: "gate",
  gate: "gate2",
  number: 2,
  title: "Confirm As-Is",
  question: "Does this match how your system works today?",
  subject: null,
  playbook: "microservices",
  tier: 3,
  summary: { as_is: { stub: true } },
  options: ["approve", "edit", "reject"],
};

function okFetch() {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 202, json: async () => ({ status: "resumed" }) });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("GateCard", () => {
  it("approves with one click", async () => {
    const fetch = okFetch();
    const onAnswered = vi.fn();
    render(<GateCard runId="r1" prompt={gate} onAnswered={onAnswered} />);
    expect(screen.getByText("Gate 2: Confirm As-Is")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(onAnswered).toHaveBeenCalled());
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/runs/r1/answer");
    expect(JSON.parse(init.body)).toEqual({ decision: "approve", comment: "" });
  });

  it("requires a comment to reject, then sends it", async () => {
    const fetch = okFetch();
    render(<GateCard runId="r1" prompt={gate} onAnswered={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("need a comment");
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Comment/), { target: { value: "Payment also calls Notification" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      decision: "reject",
      comment: "Payment also calls Notification",
    });
  });

  it("warns plainly when a step did not pass, instead of looking like a routine approval", () => {
    okFetch();
    render(<GateCard runId="r1" prompt={gate} onAnswered={vi.fn()} hasFailedStep />);
    expect(screen.getByRole("alert")).toHaveTextContent("did not pass");
  });

  it("shows no such warning when every step passed", () => {
    okFetch();
    render(<GateCard runId="r1" prompt={gate} onAnswered={vi.fn()} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("LLMUnavailableCard", () => {
  const prompt: LLMUnavailablePrompt = {
    kind: "llm_unavailable",
    step: "intake",
    profile: "remote_gpu",
    error: "ConnectError: no route to host",
    options: ["retry", "switch_to_cpu"],
  };

  it("offers retry and switching to the CPU", async () => {
    const fetch = okFetch();
    render(<LLMUnavailableCard runId="r1" prompt={prompt} onAnswered={vi.fn()} />);
    expect(screen.getByText("Remote GPU model server is unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch to local CPU" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ choice: "switch_to_cpu" });
  });

  it("only offers retry when already on the CPU", () => {
    render(
      <LLMUnavailableCard
        runId="r1"
        prompt={{ ...prompt, profile: "local_cpu", options: ["retry"] }}
        onAnswered={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Switch to local CPU" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("BudgetCard", () => {
  const prompt: BudgetPrompt = {
    kind: "budget_exceeded",
    step: "work",
    reason: "Used 20 of 20 LLM calls in step work.",
    used: { llm_calls: 20 },
    options: ["continue", "stop"],
  };

  it("shows the reason and stops the run on request", async () => {
    const fetch = okFetch();
    render(<BudgetCard runId="r1" prompt={prompt} onAnswered={vi.fn()} />);
    expect(screen.getByText("Budget reached at step work")).toBeInTheDocument();
    expect(screen.getByText(/Used 20 of 20 LLM calls/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop run" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ choice: "stop" });
  });
});
