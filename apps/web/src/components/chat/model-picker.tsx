"use client";

import { useEffect, useState } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getSettings, PROFILE_LABEL, updateLLMSettings, type ProfileName } from "@/lib/api";

/** Fired when the active model profile changes, so the sidebar's model status refreshes. */
export const LLM_CHANGED = "codewright:llm-changed";

/** The chat's model picker (Section 2.2): switches the active LLM profile for new replies and runs. */
export function ModelPicker() {
  const [profile, setProfile] = useState<ProfileName | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setProfile(s.active_llm_profile))
      .catch(() => setProfile(null));
  }, []);

  if (!profile) return null;
  return (
    <Select
      value={profile}
      items={PROFILE_LABEL}
      onValueChange={(v) => {
        if (v !== "remote_gpu" && v !== "local_cpu") return;
        setProfile(v);
        void updateLLMSettings({ active_profile: v }).then(() => window.dispatchEvent(new Event(LLM_CHANGED)));
      }}
    >
      <SelectTrigger size="sm" aria-label="Model" className="text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false} align="end">
        {(Object.keys(PROFILE_LABEL) as ProfileName[]).map((p) => (
          <SelectItem key={p} value={p}>
            {PROFILE_LABEL[p]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
