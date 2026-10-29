import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  deliver: vi.fn(),
  getConnectors: vi.fn().mockResolvedValue({
    github_token: false,
    drive: { connected: false },
    output_folder: "/out",
  }),
}));

import { DeliverPanel } from "./deliver-panel";

describe("DeliverPanel", () => {
  it("offers the places as one dropdown of checkboxes, with why one is not available yet", async () => {
    render(<DeliverPanel runId="r1" />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Download as ZIP/ }));
    expect(await screen.findByRole("menuitemcheckbox", { name: "Download as ZIP" })).toBeChecked();
    expect(
      screen.getByRole("menuitemcheckbox", { name: /GitHub pull request \(needs GITHUB_TOKEN/ }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("menuitemcheckbox", { name: /Google Drive: upload as a folder \(connect Drive/ }),
    ).toBeInTheDocument();
  });
});
