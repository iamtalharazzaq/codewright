import type { Metadata } from "next";

import { SettingsView } from "@/components/settings/settings-view";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <section aria-labelledby="settings-heading" className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 id="settings-heading" className="font-heading text-2xl font-semibold tracking-tight">
          Settings
        </h1>
        <p className="text-sm text-muted-foreground">Model servers, connection checks and privacy.</p>
      </header>
      <SettingsView />
    </section>
  );
}
