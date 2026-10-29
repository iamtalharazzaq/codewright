import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "@/lib/api";

import { PlanTab, intakeRows } from "./plan-tab";

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getRun: vi.fn().mockResolvedValue({
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
    expect(rows.map((r) => [r.id, r.status])).toEqual([
      ["gather", "in_progress"],
      ["confirm", "pending"],
    ]);
    expect(rows[0].role).toBe("product_manager");
  });

  it("marks the Product Manager done once the details are gathered, then waits for the user to confirm", () => {
    const rows = intakeRows([msg("questions"), msg("confirm", "open")], false);
    expect(rows.map((r) => r.status)).toEqual(["done", "in_progress"]);
    expect(intakeRows([msg("questions"), msg("confirm", "started")], true).map((r) => r.status)).toEqual([
      "done",
      "done",
    ]);
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
});
