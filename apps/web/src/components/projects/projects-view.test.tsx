import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Connectors, Project } from "@/lib/api";

import { ProjectsView } from "./projects-view";

const CONNECTORS: Connectors = {
  github_token: false,
  local_folders: ["goshop"],
  output_folder: true,
  drive: { configured: false, connected: false },
};

/** `/api/connectors` always answers; `/api/projects` answers with `projects` in order. */
function mockApi(...projects: Array<{ ok: boolean; status?: number; body?: unknown }>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/connectors") return { ok: true, status: 200, json: async () => CONNECTORS };
    if (url === "/api/projects" && init?.method === "POST") {
      return { ok: true, status: 201, json: async () => ({ id: "new" }) };
    }
    const r = projects.length > 1 ? projects.shift()! : projects[0];
    return { ok: r.ok, status: r.status ?? 200, json: async () => r.body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("ProjectsView", () => {
  it("shows the new-project form when there are no projects", async () => {
    const fetch = mockApi({ ok: true, body: [] });
    render(<ProjectsView />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading projects");
    expect(await screen.findByText("New project")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
    expect(fetch).toHaveBeenCalledWith("/api/projects", expect.anything());
  });

  it("connects a local folder", async () => {
    const fetch = mockApi({ ok: true, body: [] });
    render(<ProjectsView />);
    fireEvent.click(await screen.findByRole("radio", { name: "Local folder" }));
    fireEvent.click(await screen.findByRole("button", { name: "goshop" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await vi.waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/projects", expect.objectContaining({ method: "POST" })),
    );
    const form = fetch.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body as FormData;
    expect(form.get("kind")).toBe("local");
    expect(form.get("ref")).toBe("goshop");
  });

  it("lists projects with their status", async () => {
    const project: Project = {
      id: "p1",
      name: "goshop",
      status: "ready",
      source: { kind: "github", ref: "https://github.com/quangdangfit/goshop" },
      summary: { files: 371, languages: { Go: 260 } },
      error: null,
      created_at: "2026-10-26T10:00:00Z",
      updated_at: "2026-10-26T10:00:00Z",
    };
    mockApi({ ok: true, body: [project] });
    render(<ProjectsView />);
    expect(await screen.findByText("goshop")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText(/371 files/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /goshop/ })).toHaveAttribute("href", "/projects/p1");
  });

  it("shows an error with a working retry when the API is down", async () => {
    mockApi({ ok: false, status: 502 }, { ok: true, body: [] });
    render(<ProjectsView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the Codewright API");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("New project")).toBeInTheDocument();
  });
});
