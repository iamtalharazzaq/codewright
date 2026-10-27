"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getGraph, type ProjectGraph } from "@/lib/api";

/**
 * A project's module graph, kept live (CODEWRIGHT.md Section 8.2): the API sends `working` (modules being changed),
 * `graph_building` and `graph` (a new version) on `/api/projects/<id>/events`. While `live`, each new version is
 * shown as it arrives; picking an older version on the timeline stops following until "Live" is pressed.
 */
export function useProjectGraph(projectId: string) {
  const [data, setData] = useState<ProjectGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<string[]>([]);
  const [building, setBuilding] = useState(false);
  const [live, setLive] = useState(true);
  const liveRef = useRef(true);

  const load = useCallback(
    async (version?: number | null) => {
      try {
        const graph = await getGraph(projectId, version);
        setData(graph);
        setBuilding(graph.building);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [projectId],
  );

  useEffect(() => {
    // Load now, and again whenever the stream (re)connects so nothing missed while offline stays missed.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading data on mount
    void load(null);
    const source = new EventSource(`/api/projects/${projectId}/events`);
    source.addEventListener("ready", () => void load(liveRef.current ? null : undefined));
    source.addEventListener("working", (e) => setWorking((JSON.parse(e.data) as { modules: string[] }).modules));
    source.addEventListener("graph_building", () => setBuilding(true));
    source.addEventListener("graph", () => {
      setBuilding(false);
      setWorking([]);
      if (liveRef.current) void load(null);
      else void getGraph(projectId).then((g) => setData((d) => (d ? { ...d, versions: g.versions } : g)));
    });
    source.addEventListener("graph_error", (e) => {
      setBuilding(false);
      setError((JSON.parse(e.data) as { error: string }).error);
    });
    return () => source.close();
  }, [projectId, load]);

  const showVersion = useCallback(
    (version: number) => {
      const latest = data?.versions.at(-1)?.number;
      liveRef.current = version === latest;
      setLive(version === latest);
      void load(version);
    },
    [data, load],
  );

  const goLive = useCallback(() => {
    liveRef.current = true;
    setLive(true);
    void load(null);
  }, [load]);

  return { data, error, working, building, live, showVersion, goLive, reload: load };
}
