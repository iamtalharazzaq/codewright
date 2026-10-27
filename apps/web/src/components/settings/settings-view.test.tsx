import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { HealthView, SettingsView as Settings } from "@/lib/api";

import { SettingsView } from "./settings-view";

const profile = (base_url: string | null) => ({
  server: "llamacpp",
  base_url,
  model: "Qwen3.5-9B-Q4_K_M",
  num_ctx: 4096,
  max_parallel_llm_jobs: 1,
  configured: base_url !== null,
  api_key_configured: false,
});

const settings: Settings = {
  active_llm_profile: "local_cpu",
  llm_profiles: { remote_gpu: profile(null), local_cpu: profile("http://host.docker.internal:8080/v1") },
  embeddings_model: "Qwen3-Embedding-0.6B",
  external_llm_enabled: false,
};

const health: HealthView[] = [
  {
    profile: "remote_gpu",
    status: "not_configured",
    base_url: null,
    latency_ms: null,
    server_model: null,
    server_ctx: null,
    server_slots: null,
    warnings: [],
    detail: "No URL set for this profile.",
  },
  {
    profile: "local_cpu",
    status: "ok",
    base_url: "http://host.docker.internal:8080/v1",
    latency_ms: 12,
    server_model: "m",
    server_ctx: 4096,
    server_slots: 4,
    warnings: [],
    detail: null,
  },
];

function mockApi() {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const body = url.endsWith("/llm/health")
      ? health
      : url.endsWith("/settings/llm")
        ? { ...settings, ...JSON.parse(String(init?.body)), active_llm_profile: "remote_gpu" }
        : settings;
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("SettingsView", () => {
  it("shows both profiles with their health", async () => {
    mockApi();
    render(<SettingsView />);
    expect(await screen.findByText("Reachable in 12 ms · 4 slots × 4096 tokens")).toBeInTheDocument();
    expect(screen.getByText("No URL set for this profile.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Local CPU/ })).toBeChecked();
  });

  it("switches the active profile", async () => {
    const fetch = mockApi();
    render(<SettingsView />);
    fireEvent.click(await screen.findByRole("radio", { name: /Remote GPU/ }));
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/settings/llm"))).toBe(true));
    const put = fetch.mock.calls.find(([url]) => String(url).endsWith("/settings/llm"));
    expect(put?.[1]?.method).toBe("PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ active_profile: "remote_gpu" });
  });

  it("saves a new server URL for a profile", async () => {
    const fetch = mockApi();
    render(<SettingsView />);
    const url = await screen.findByLabelText("Server URL", { selector: "#profile-remote_gpu-url" });
    fireEvent.change(url, { target: { value: "http://100.64.0.5:8080/v1" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(fetch.mock.calls.some(([u]) => String(u).endsWith("/settings/llm"))).toBe(true));
    const put = fetch.mock.calls.find(([u]) => String(u).endsWith("/settings/llm"));
    expect(JSON.parse(String(put?.[1]?.body)).profiles.remote_gpu.base_url).toBe("http://100.64.0.5:8080/v1");
  });
});
