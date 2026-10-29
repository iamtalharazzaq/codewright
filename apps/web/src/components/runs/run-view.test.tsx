import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Playbook, RunDetail } from "@/lib/api";

import { RunView } from "./run-view";

/** The RunView subscribes to SSE on mount; this stub just needs to exist and never fire. */
class FakeEventSource {
  addEventListener() {}
  close() {}
}

const PLAYBOOK: Playbook = {
  name: "new_app",
  title: "New App",
  description: "Builds a new app from scratch.",
  intent: null,
  lead_role: "project_manager",
  tier: 1,
  steps: [
    { id: "scaffold", title: "Scaffold", role: "backend_developer", number: 1 },
    { id: "verify", title: "Run the tests", role: "qa_engineer", number: 2 },
  ],
  gates: [],
  inputs_schema: {},
};

const BASE_RUN: RunDetail = {
  id: "r1",
  project_id: "p1",
  playbook: "new_app",
  tier: 1,
  status: "completed",
  llm_profile: "remote_gpu",
  inputs: {},
  current_step: null,
  pending: null,
  error: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  usage: { prompt_tokens: 0, completion_tokens: 0, llm_calls: 0, llm_time_ms: 0 },
  approvals: [],
  flow: ["scaffold", "verify"],
  plan: [
    { id: "scaffold", title: "Scaffold", role: "backend_developer", status: "done" },
    { id: "verify", title: "Run the tests", role: "qa_engineer", status: "failed" },
  ],
  steps: {
    scaffold: { status: "done", summary: "written" },
    verify: { status: "failed", summary: "tests failing: tests.test_core: collection failure" },
  },
  artifacts: [],
  budget: null,
};

function mockApi(run: RunDetail) {
  const fn = vi.fn(async (url: string) => {
    if (url === "/api/playbooks/new_app") return { ok: true, status: 200, json: async () => PLAYBOOK };
    if (url === "/api/runs/r1") return { ok: true, status: 200, json: async () => run };
    if (url.startsWith("/api/traces")) return { ok: true, status: 200, json: async () => [] };
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal("fetch", fn);
  vi.stubGlobal("EventSource", FakeEventSource);
  return fn;
}

describe("RunView", () => {
  it("never shows a failed step as done, even once the run itself reads completed", async () => {
    mockApi(BASE_RUN);
    render(<RunView runId="r1" />);
    expect(await screen.findByText("2. Run the tests")).toBeInTheDocument();
    // The run-level badge must not read as a clean "Completed" when a step failed.
    expect(screen.getByText(/a step failed/)).toBeInTheDocument();
    // Both the Timeline icon and the Plan checklist icon carry a failed label for this step (sr-only text).
    expect(screen.getByText("Failed:")).toBeInTheDocument();
    expect(screen.getByText("failed:")).toBeInTheDocument();
  });

  it("shows a clean completed run with no failure warnings", async () => {
    const run: RunDetail = {
      ...BASE_RUN,
      plan: BASE_RUN.plan.map((p) => ({ ...p, status: "done" })),
      steps: { scaffold: { status: "done" }, verify: { status: "done", summary: "3 test(s) passed" } },
    };
    mockApi(run);
    render(<RunView runId="r1" />);
    await screen.findByText("2. Run the tests");
    expect(screen.queryByText(/a step failed/)).not.toBeInTheDocument();
  });

  it("shows a role without underscores, even one with no hand-written label", async () => {
    const run: RunDetail = {
      ...BASE_RUN,
      plan: [
        { id: "scaffold", title: "Scaffold", role: "product_manager", status: "done" },
        { id: "verify", title: "Run the tests", role: "security_engineer", status: "done" },
      ],
    };
    mockApi(run);
    render(<RunView runId="r1" />);
    await screen.findByText("2. Run the tests");
    expect(screen.getAllByText("Product Manager").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Security Engineer").length).toBeGreaterThan(0);
    expect(screen.queryByText("product_manager")).not.toBeInTheDocument();
    expect(screen.queryByText("security_engineer")).not.toBeInTheDocument();
  });
});
