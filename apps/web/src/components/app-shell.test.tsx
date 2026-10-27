import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./app-shell";
import { ThemeProvider } from "./theme-provider";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));

const SETTINGS = {
  active_llm_profile: "remote_gpu",
  llm_profiles: { remote_gpu: { model: "Qwen3.5-9B-Q4_K_M" }, local_cpu: { model: "Qwen3.5-9B-Q4_K_M" } },
  embeddings_model: "e",
  external_llm_enabled: false,
};

function stubApi(projects: unknown[] = [], healthStatus = "ok") {
  const fn = vi.fn((url: string) => {
    const body = url.startsWith("/api/projects")
      ? projects
      : url.startsWith("/api/settings")
        ? SETTINGS
        : [{ profile: "remote_gpu", status: healthStatus, warnings: [] }];
    return Promise.resolve({ ok: true, status: 200, json: async () => body });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderShell() {
  return render(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <AppShell>
        <p>content</p>
      </AppShell>
    </ThemeProvider>,
  );
}

describe("AppShell", () => {
  it("renders the Claude-style sidebar, a skip link and the main area", async () => {
    stubApi();
    renderShell();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("link", { name: "New chat" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "All projects" })).toHaveAttribute("href", "/projects");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
    expect(screen.getByRole("region", { name: "Chats" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Theme:/ })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("content");
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  });

  it("lists projects and shows the active model with its health", async () => {
    stubApi([{ id: "p1", name: "GoShop", status: "draft", created_at: "", updated_at: "" }]);
    renderShell();
    expect(await screen.findByRole("link", { name: "GoShop" })).toBeInTheDocument();
    expect(await screen.findByText("Remote GPU · Qwen3.5-9B-Q4_K_M")).toBeInTheDocument();
    expect(await screen.findByText(/Model server: ok/)).toBeInTheDocument();
  });

  it("opens and closes the sidebar drawer on small screens", () => {
    stubApi();
    renderShell();
    const open = screen.getByRole("button", { name: "Open sidebar" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getAllByRole("button", { name: "Close sidebar" })[0]);
    expect(open).toHaveAttribute("aria-expanded", "false");
  });
});
