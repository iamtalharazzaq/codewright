"use client";

import type { Core, ElementDefinition } from "cytoscape";
import { useEffect, useRef } from "react";

import type { GraphDiff, ProjectGraph } from "@/lib/api";

export const STATE_COLORS = {
  added: "#16a34a",
  changed: "#d97706",
  removed: "#dc2626",
  working: "#2563eb",
  highlight: "#7c3aed",
} as const;

function elements(
  graph: NonNullable<ProjectGraph["graph"]>,
  diff: GraphDiff | null,
  working: string[],
  highlight: string[],
  hidden: Set<string>,
): ElementDefinition[] {
  const added = new Set(diff?.added ?? []);
  const changed = new Set(diff?.changed ?? []);
  const newEdges = new Set(diff?.edges_added ?? []);
  const nodes: ElementDefinition[] = graph.nodes
    .filter((n) => !hidden.has(n.id))
    .map((n) => ({
      data: { id: n.id, label: n.id, size: 18 + Math.min(42, Math.sqrt(n.symbols) * 2.5) },
      classes: [
        added.has(n.id) && "added",
        changed.has(n.id) && "changed",
        working.includes(n.id) && "working",
        highlight.includes(n.id) && "highlight",
      ]
        .filter(Boolean)
        .join(" "),
    }));
  // Removed modules stay visible as faded ghosts until the next version.
  for (const id of diff?.removed ?? []) {
    nodes.push({ data: { id, label: id, size: 18 }, classes: "removed" });
  }
  const ids = new Set(nodes.map((n) => n.data.id));
  const edges: ElementDefinition[] = graph.edges
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => ({
      data: {
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        width: 1 + Math.min(5, Math.log2(1 + e.weight)),
      },
      classes: [
        newEdges.has(`${e.source}->${e.target}`) && "added",
        e.weight === 0 && !e.user_fact && "inferred",
        e.user_fact && "fact",
        e.disputed && "disputed",
      ]
        .filter(Boolean)
        .join(" "),
    }));
  return [...nodes, ...edges];
}

/** The module graph drawn with Cytoscape.js. Positions are kept between updates so a growing graph doesn't jump. */
export function GraphCanvas({
  graph,
  diff,
  working = [],
  highlight = [],
  hidden = new Set<string>(),
  selected,
  onSelect,
  className,
}: {
  graph: NonNullable<ProjectGraph["graph"]>;
  diff: GraphDiff | null;
  working?: string[];
  highlight?: string[];
  hidden?: Set<string>;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const select = useRef(onSelect);
  useEffect(() => {
    select.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    let disposed = false;
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (disposed || !container.current) return;
      // Cytoscape can't read CSS variables or oklch(), so pick plain colors for the theme.
      const dark = document.documentElement.classList.contains("dark");
      const text = dark ? "#e5e7eb" : "#1f2937";
      const halo = dark ? "#0a0a0a" : "#ffffff";
      const instance = cytoscape({
        container: container.current,
        minZoom: 0.2,
        maxZoom: 1.4,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "#64748b",
              label: "data(label)",
              color: text,
              "font-size": 10,
              "text-valign": "bottom",
              "text-margin-y": 4,
              "text-outline-color": halo,
              "text-outline-width": 2,
              width: "data(size)",
              height: "data(size)",
              "border-width": 0,
            },
          },
          {
            selector: "edge",
            style: {
              width: "data(width)",
              "line-color": "#94a3b8",
              "target-arrow-color": "#94a3b8",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              opacity: 0.45,
            },
          },
          { selector: "edge.inferred", style: { "line-style": "dashed" } },
          // Your corrections (USER_FACT): a fact you added is solid and strong; a link you said is wrong is dotted.
          {
            selector: "edge.fact",
            style: { "line-color": STATE_COLORS.highlight, "target-arrow-color": STATE_COLORS.highlight, opacity: 0.9 },
          },
          {
            selector: "edge.disputed",
            style: {
              "line-style": "dotted",
              "line-color": STATE_COLORS.removed,
              "target-arrow-color": STATE_COLORS.removed,
            },
          },
          {
            selector: "edge.added",
            style: { "line-color": STATE_COLORS.added, "target-arrow-color": STATE_COLORS.added },
          },
          { selector: "node.added", style: { "background-color": STATE_COLORS.added } },
          { selector: "node.changed", style: { "background-color": STATE_COLORS.changed } },
          {
            selector: "node.removed",
            style: { "background-color": STATE_COLORS.removed, opacity: 0.35, "border-style": "dashed" },
          },
          {
            selector: "node.working",
            style: { "border-width": 4, "border-color": STATE_COLORS.working, "border-style": "double" },
          },
          { selector: "node.highlight", style: { "border-width": 3, "border-color": STATE_COLORS.highlight } },
          { selector: "node:selected", style: { "border-width": 3, "border-color": text } },
        ],
      });
      instance.on("tap", "node", (e) => select.current?.(e.target.id()));
      instance.on("tap", (e) => {
        if (e.target === instance) select.current?.(null);
      });
      instance.on("dragfree", "node", (e) => positions.current.set(e.target.id(), { ...e.target.position() }));
      cy.current = instance;
      container.current.dispatchEvent(new Event("cy-ready"));
    });
    return () => {
      disposed = true;
      cy.current?.destroy();
      cy.current = null;
    };
  }, []);

  useEffect(() => {
    const el = container.current;
    function draw() {
      const instance = cy.current;
      if (!instance) return;
      const els = elements(graph, diff, working, highlight, hidden);
      const known = positions.current;
      const fresh = els.some((e) => !e.data.source && !known.has(e.data.id!));
      instance.batch(() => {
        instance.elements().remove();
        instance.add(els.map((e) => (known.has(e.data.id!) ? { ...e, position: known.get(e.data.id!) } : e)));
      });
      if (fresh) {
        const layout = instance.layout({
          name: "cose",
          animate: false,
          randomize: known.size === 0,
          nodeRepulsion: () => 40000,
          idealEdgeLength: () => 140,
          nodeOverlap: 20,
          fit: true,
          padding: 24,
        });
        layout.one("layoutstop", () => instance.nodes().forEach((n) => void known.set(n.id(), { ...n.position() })));
        layout.run();
      }
      if (selected) instance.getElementById(selected).select();
    }
    draw();
    el?.addEventListener("cy-ready", draw);
    return () => el?.removeEventListener("cy-ready", draw);
  }, [graph, diff, working, highlight, hidden, selected]);

  return <div ref={container} className={className} role="img" aria-label="Module graph" />;
}
