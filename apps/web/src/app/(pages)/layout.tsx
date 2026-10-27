import type { ReactNode } from "react";

// Full-page screens (Projects, Runs, Settings) scroll inside the shell with comfortable margins;
// the chat screen at `/` manages its own layout.
export default function PagesLayout({ children }: { children: ReactNode }) {
  return (
    <div className="h-full overflow-y-auto px-4 py-6 sm:px-8 sm:py-10">
      <div className="mx-auto w-full max-w-5xl">{children}</div>
    </div>
  );
}
