import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Preview, SandboxActivity, SandboxStatus } from "@/lib/api";

import { PreviewView } from "./preview-view";
import { SandboxPanel } from "./sandbox-panel";

const STATUS: SandboxStatus = {
  runner: { docker: true, gateway: true, images: { python: true, go: true, node: true, cpp: true } },
  components: [
    {
      pack: "go",
      path: ".",
      kind: "api",
      frameworks: ["gin", "gorm"],
      entrypoints: ["./cmd/api"],
      manifest: "go.mod",
      run: { kind: "web", cmd: ["./.codewright/bin/app"], port: 8888, services: ["postgres", "redis"] },
    },
    {
      pack: "typescript",
      path: "web",
      kind: "web",
      frameworks: ["react", "vite"],
      entrypoints: [],
      manifest: "package.json",
      run: null,
    },
  ],
  session: null,
  activities: [],
};

/** Replays activity events through a fake EventSource. */
class FakeEventSource {
  static last: FakeEventSource | null = null;
  listeners: Record<string, ((e: MessageEvent<string>) => void)[]> = {};
  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: (e: MessageEvent<string>) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? []) fn({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
  close() {}
}

function mockApi() {
  const activity: SandboxActivity = {
    id: "a1",
    action: "test",
    components: ["."],
    status: "running",
    started_at: 0,
    finished_at: null,
    results: [],
    previews: [],
    error: null,
  };
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/sandbox/actions") && init?.method === "POST") {
      return { ok: true, status: 202, json: async () => activity };
    }
    return { ok: true, status: 200, json: async () => STATUS };
  });
  vi.stubGlobal("fetch", fn);
  vi.stubGlobal("EventSource", FakeEventSource);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("SandboxPanel", () => {
  it("lists components by Language Pack and streams a test run with its report", async () => {
    const fetch = mockApi();
    render(<SandboxPanel projectId="p1" />);
    expect(await screen.findByText("Go")).toBeInTheDocument();
    expect(screen.getByText("TypeScript")).toBeInTheDocument();
    expect(screen.getByText("gin · gorm")).toBeInTheDocument();
    // `web` has nothing to run: no Run button on its row
    expect(screen.getByRole("button", { name: "Run root" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run web" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Test root" }));
    await vi.waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/projects/p1/sandbox/actions",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await vi.waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/projects/p1/sandbox/actions/a1/events"));
    const es = FakeEventSource.last!;
    es.emit("step", { name: "test", cmd: ["go", "test", "-json", "./..."], network: "none" });
    es.emit("output", { text: "--- FAIL: TestPay\n" });
    es.emit("step_done", { result: { ok: false, duration_s: 3.2 } });
    es.emit("report", {
      report: {
        tool: "go test",
        passed: 341,
        failed: 1,
        skipped: 0,
        errors: 0,
        total: 342,
        ok: false,
        found: true,
        cases: [{ name: "payment::TestPay", status: "failed", message: "want 2", file: "" }],
      },
    });
    es.emit("done", { status: "failed", error: null });

    expect(await screen.findByText("341 passed")).toBeInTheDocument();
    expect(screen.getByText("1 failed")).toBeInTheDocument();
    expect(screen.getByText("payment::TestPay")).toBeInTheDocument();
    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.getByText(/--- FAIL: TestPay/)).toBeInTheDocument();
  });
});

describe("PreviewView", () => {
  it("frames a web preview and switches between previews", () => {
    const preview = (id: string, name: string, port: number): Preview => ({
      id,
      session: "s",
      kind: "web",
      name,
      cmd: [name],
      port,
      url: `http://localhost:${41000 + (id === "a" ? 0 : 1)}/`,
      running: true,
      exit_code: null,
      started_at: 0,
    });
    const previews = [preview("a", "api", 8888), preview("b", "web", 5173)];
    render(<PreviewView projectId="p1" previews={previews} onStop={async () => {}} />);
    expect(screen.getByTitle("Preview: web")).toHaveAttribute("src", "http://localhost:41001/");
    fireEvent.click(screen.getByRole("button", { name: "api" }));
    expect(screen.getByTitle("Preview: api")).toHaveAttribute("src", "http://localhost:41000/");
    expect(screen.getByRole("link", { name: "Open preview in a new tab" })).toHaveAttribute(
      "href",
      "http://localhost:41000/",
    );
  });

  it("says how to get a preview when nothing runs", () => {
    render(<PreviewView projectId="p1" previews={[]} onStop={async () => {}} />);
    expect(screen.getByText("Run the project to see it here.")).toBeInTheDocument();
  });
});
