import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppShell } from "./app-shell";
import { ThemeProvider } from "./theme-provider";

describe("AppShell", () => {
  it("renders navigation, a skip link and the theme toggle", () => {
    render(
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <AppShell>
          <p>content</p>
        </AppShell>
      </ThemeProvider>,
    );
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("button", { name: /^Theme:/ })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("content");
  });
});
