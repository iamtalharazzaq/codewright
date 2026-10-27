import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatView } from "./chat-view";
import { Composer } from "./composer";
import { PANEL_TABS } from "./side-panel";

describe("ChatView", () => {
  it("shows the welcome, suggestions and a composer that can't send yet", () => {
    render(<ChatView />);
    expect(screen.getByRole("heading", { name: "What are we building today?" })).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Message Codewright" });
    expect(input).toHaveAccessibleDescription(/Chat replies arrive in Phase 2/);
    fireEvent.click(screen.getByRole("button", { name: "What's a saga pattern?" }));
    expect(input).toHaveValue("What's a saga pattern?");
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("has a side panel with the seven artifact tabs that can be hidden and shown", () => {
    render(<ChatView />);
    const tabs = within(screen.getByRole("tablist", { name: "Artifacts" })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Plan", "Diff", "Graph", "Diagram", "Tests", "Preview", "Report"]);
    expect(PANEL_TABS).toHaveLength(7);

    fireEvent.click(screen.getByRole("tab", { name: "Graph" }));
    expect(screen.getByText("The project's live Graphify graph appears here.")).toBeVisible();

    // jsdom matches no media queries, so the panel starts as on a small screen: hidden.
    const toggle = screen.getByRole("button", { name: "Show side panel" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide side panel" })).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Close side panel" }));
    expect(screen.getByRole("button", { name: "Show side panel" })).toBeInTheDocument();
  });
});

describe("Composer", () => {
  it("sends on Enter, adds a line on Shift+Enter, and ignores blank messages", () => {
    const onSend = vi.fn();
    const { rerender } = render(<Composer value="  " onChange={() => {}} onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: "Message Codewright" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();

    rerender(<Composer value=" explain checkout " onChange={() => {}} onSend={onSend} />);
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("explain checkout");
  });
});
