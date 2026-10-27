import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/api";

import { ProjectsView } from "./projects-view";

function mockFetch(...responses: Array<{ ok: boolean; status?: number; body?: unknown } | Error>) {
  const fn = vi.fn();
  for (const r of responses) {
    if (r instanceof Error) fn.mockRejectedValueOnce(r);
    else fn.mockResolvedValueOnce({ ok: r.ok, status: r.status ?? 200, json: async () => r.body });
  }
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("ProjectsView", () => {
  it("shows the empty state when there are no projects", async () => {
    const fetch = mockFetch({ ok: true, body: [] });
    render(<ProjectsView />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading projects");
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New project" })).toBeDisabled();
    expect(fetch).toHaveBeenCalledWith("/api/projects", expect.anything());
  });

  it("lists projects with their status", async () => {
    const project: Project = {
      id: "p1",
      name: "goshop",
      status: "draft",
      created_at: "2026-10-26T10:00:00Z",
      updated_at: "2026-10-26T10:00:00Z",
    };
    mockFetch({ ok: true, body: [project] });
    render(<ProjectsView />);
    expect(await screen.findByText("goshop")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
  });

  it("shows an error with a working retry when the API is down", async () => {
    mockFetch({ ok: false, status: 502 }, { ok: true, body: [] });
    render(<ProjectsView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the Codewright API");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  });
});
