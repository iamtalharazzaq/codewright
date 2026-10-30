import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "@/lib/api";

import { PlanTab, intakeRows } from "./plan-tab";

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  listTraces: vi
    .fn()
    .mockResolvedValue([{ step: "build", prompt_tokens: 100, completion_tokens: 50, latency_ms: 2000 }]),
  getRun: vi.fn().mockResolvedValue({
    steps: { requirements: { status: "done", summary: "Calc: 3 features" }, build: { summary: "4 file(s) written" } },
    artifacts: [{ kind: "file", title: "Requirements", path: "r.md", step: "requirements" }],
    plan: [
      { id: "requirements", title: "Requirements and the first version", role: "product_manager", status: "done" },
      { id: "build", title: "Build the app", role: "backend_developer", status: "in_progress" },
    ],
  }),
}));

function msg(kind: ChatMessage["kind"], state?: "open" | "started"): ChatMessage {
  return {
    id: kind,
    conversation_id: "c1",
    parent_id: null,
    role: "assistant",
    kind,
    content: "",
    data: { state },
    status: "complete",
    run_id: null,
    created_at: "2026-01-01T00:00:00Z",
    siblings: [],
  };
}

describe("intakeRows", () => {
  it("has nothing before the request has been looked at", () => {
    expect(intakeRows([], false)).toEqual([]);
  });

  it("keeps the Product Manager in progress while the questions are open", () => {
    const rows = intakeRows([msg("questions")], false);
    expect(rows.map((r) => [r.id, r.status])).toEqual([["gather", "in_progress"]]);
    expect(rows[0].role).toBe("product_manager");
  });

  it("marks the Product Manager done once the details are gathered; confirming is not a step", () => {
    expect(intakeRows([msg("questions"), msg("confirm", "open")], false).map((r) => r.status)).toEqual(["done"]);
    expect(intakeRows([msg("questions"), msg("confirm", "started")], true).map((r) => r.id)).toEqual(["gather"]);
  });
});

describe("PlanTab", () => {
  it("shows who has the request, with role names and no underscores, then the run's steps", async () => {
    render(<PlanTab messages={[msg("questions"), msg("confirm", "started")]} runId="r1" runTick={0} />);
    expect(await screen.findByText("Build the app")).toBeInTheDocument();
    expect(screen.getByText("Gather the missing details")).toBeInTheDocument();
    expect(screen.getAllByText("Product Manager").length).toBeGreaterThan(0);
    expect(screen.getByText("Backend Developer")).toBeInTheDocument();
    expect(screen.queryByText("product_manager")).not.toBeInTheDocument();
  });

  it("opens a modal from a step: where the request came from, where it went, and how it worked", async () => {
    render(<PlanTab messages={[msg("questions"), msg("confirm", "started")]} runId="r1" runTick={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /Build the app/ }));
    expect(await screen.findByText("Received from")).toBeInTheDocument();
    expect(
      screen.getByText(/Product Manager \(Requirements and the first version\): Calc: 3 features/),
    ).toBeInTheDocument();
    expect(screen.getByText("Nobody: this is the last step.")).toBeInTheDocument();
    expect(await screen.findByText("4 file(s) written")).toBeInTheDocument();
    expect(await screen.findByText(/1 model call · 150 tokens · 2.0s/)).toBeInTheDocument();
  });
});
