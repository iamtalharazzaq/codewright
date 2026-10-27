import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectGraph } from "@/lib/api";

import { GraphView } from "./graph-view";

// Cytoscape needs a real canvas; the canvas itself is covered in the browser.
vi.mock("@/components/graph/graph-canvas", () => ({
  STATE_COLORS: { added: "g", changed: "o", removed: "r", working: "b", highlight: "p" },
  GraphCanvas: ({ graph, onSelect }: { graph: ProjectGraph["graph"]; onSelect: (id: string) => void }) => (
    <ul aria-label="canvas">
      {graph!.nodes.map((n) => (
        <li key={n.id}>
          <button onClick={() => onSelect(n.id)}>{`node ${n.id}`}</button>
        </li>
      ))}
    </ul>
  ),
}));

class FakeEventSource {
  addEventListener() {}
  close() {}
}

const version = (number: number) => ({
  number,
  created_at: 0,
  reason: "build",
  nodes: 10,
  edges: 5,
  modules: 2,
  diff: { added: [], changed: [], removed: [], edges_added: [], edges_removed: [] },
  hygiene: { code_files: 3, files_without_symbols: [], isolated_modules: [], mutual_dependencies: [] },
});

function mockGraph(body: ProjectGraph) {
  const fn = vi.fn(async () => ({ ok: true, status: 200, json: async () => body }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));

describe("GraphView", () => {
  it("offers to build a graph when there is none", async () => {
    const fetch = mockGraph({ versions: [], version: null, graph: null, building: false });
    render(<GraphView projectId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Build graph" }));
    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/graph", expect.objectContaining({ method: "POST" }));
  });

  it("shows modules, the timeline and a module's dependencies", async () => {
    mockGraph({
      versions: [version(1), version(2)],
      version: 2,
      building: false,
      graph: {
        nodes: [
          { id: "internal/order", label: "order", files: ["a.go"], file_count: 1, symbols: 4, languages: { Go: 1 } },
          { id: "internal/user", label: "user", files: ["b.go"], file_count: 1, symbols: 2, languages: { Go: 1 } },
        ],
        edges: [
          {
            source: "internal/order",
            target: "internal/user",
            weight: 3,
            relations: { calls: 3 },
            sources: [{ source: "graphify", confidence: "EXTRACTED" }],
          },
        ],
      },
    });
    render(<GraphView projectId="p1" />);
    expect(await screen.findByText("2 modules · 1 links")).toBeInTheDocument();
    expect(screen.getByLabelText("Version 2/2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "node internal/order" }));
    expect(screen.getByText("Depends on")).toBeInTheDocument();
    expect(screen.getByText("3 refs")).toBeInTheDocument();
  });
});
