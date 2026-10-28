"use client";

import { Download, FlaskConical, Pencil, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Markdown } from "@/components/chat/markdown";
import { FormSelect } from "@/components/form-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  createSkill,
  deleteSkill,
  getConnectors,
  getSkillTemplate,
  importSkills,
  listProjects,
  listSkills,
  notifyConversationsChanged,
  replaceSkill,
  setSkillFlags,
  skillExportUrl,
  trySkill,
  type ImportResult,
  type Project,
  type Skill,
} from "@/lib/api";

const LANGUAGES = [
  { id: "python", label: "Python" },
  { id: "go", label: "Go" },
  { id: "typescript", label: "TypeScript" },
  { id: "javascript", label: "JavaScript" },
  { id: "cpp", label: "C++" },
];

interface FormState {
  name: string;
  command: string;
  title: string;
  description: string;
  playbook: string;
  languages: string[];
  tools: string[];
  autoUse: boolean;
  instructions: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  command: "",
  title: "",
  description: "",
  playbook: "custom",
  languages: [],
  tools: ["read_files", "graph_query", "code_search"],
  autoUse: true,
  instructions: "## Instructions\n1. \n\n## Output format\n",
};

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);

/** The form as SKILL.md. JSON strings and arrays are valid YAML, so values never need hand-quoting. */
function toMarkdown(f: FormState, scope: string): string {
  const name = slug(f.name || f.title);
  const front = [
    `name: ${name}`,
    `command: ${f.command ? (f.command.startsWith("/") ? f.command : `/${f.command}`) : `/${name}`}`,
    `title: ${JSON.stringify(f.title)}`,
    `description: ${JSON.stringify(f.description)}`,
    `languages: ${JSON.stringify(f.languages)}`,
    `scope: ${scope}`,
    `playbook: ${f.playbook}`,
    "tier: 0",
    `allowed_tools: ${JSON.stringify(f.tools)}`,
    "output: markdown",
    "enabled: true",
    `auto_use: ${f.autoUse}`,
  ];
  return `---\n${front.join("\n")}\n---\n\n${f.instructions.trim()}\n`;
}

function fromSkill(s: Skill): FormState {
  return {
    name: s.name,
    command: s.command,
    title: s.title,
    description: s.description,
    playbook: s.playbook,
    languages: s.languages,
    tools: s.allowed_tools,
    autoUse: s.auto_use,
    instructions: s.instructions,
  };
}

/**
 * The Skills screen (CODEWRIGHT.md Section 8.6): built-in skills (read-only), your global skills and a project's
 * skills; create with a form or in Markdown, edit, enable, auto-use, test-run, export and import.
 */
export function SkillsView() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ skill: Skill | null } | null>(null);
  const [importing, setImporting] = useState(false);
  const [trying, setTrying] = useState<Skill | null>(null);

  const load = useCallback(async () => {
    try {
      setSkills(await listSkills(projectId || null));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [projectId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading data on mount and when the scope changes
    void load();
  }, [load]);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const custom = skills.filter((s) => s.source !== "builtin");
  const builtin = skills.filter((s) => s.source === "builtin");
  const playbooks = [
    { value: "custom", label: "Custom", hint: "An answer in the chat that follows your steps" },
    ...Array.from(new Map(builtin.filter((s) => s.playbook !== "custom").map((s) => [s.playbook, s])).values()).map(
      (s) => ({ value: s.playbook, label: s.intent_label, hint: `Runs like ${s.command}` }),
    ),
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid min-w-56 gap-1.5">
          <Label htmlFor="skills-scope">Show skills for</Label>
          <FormSelect
            id="skills-scope"
            value={projectId || "global"}
            options={[
              { value: "global", label: "All projects (global)" },
              ...projects.map((p) => ({ value: p.id, label: `Project: ${p.name}` })),
            ]}
            onChange={(v) => setProjectId(v === "global" ? "" : v)}
          />
        </div>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" onClick={() => setImporting((v) => !v)}>
            <Upload aria-hidden="true" />
            Import
          </Button>
          <Button onClick={() => setEditing({ skill: null })}>
            <Plus aria-hidden="true" />
            New skill
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm whitespace-pre-line text-destructive">
          {error}
        </p>
      )}

      {importing && <ImportPanel projectId={projectId || null} onDone={() => void load()} />}
      {editing && (
        <SkillEditor
          skill={editing.skill}
          projectId={projectId || null}
          playbooks={playbooks}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
      {trying && (
        <TryPanel
          skill={trying}
          projects={projects}
          projectId={projectId || null}
          onCancel={() => setTrying(null)}
          onStarted={(id) => {
            notifyConversationsChanged();
            router.push(`/c/${id}`);
          }}
        />
      )}

      <section aria-labelledby="custom-skills" className="flex flex-col gap-3">
        <h2 id="custom-skills" className="text-sm font-medium">
          Your skills
        </h2>
        {custom.length === 0 ? (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            No skills yet. Create one here, type <code>/create-skill</code> in a chat, or say “save this as a skill”
            after a conversation you want to repeat.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {custom.map((s) => (
              <li key={`${s.source}-${s.name}`}>
                <SkillRow
                  skill={s}
                  onToggle={(flags) =>
                    void act(() => setSkillFlags(s.name, flags, s.source === "project" ? projectId : null))
                  }
                  onEdit={() => setEditing({ skill: s })}
                  onTry={() => setTrying(s)}
                  onDelete={() => {
                    if (window.confirm(`Delete the skill ${s.command}? This can't be undone.`)) {
                      void act(() => deleteSkill(s.name, s.source === "project" ? projectId : null));
                    }
                  }}
                  exportUrl={skillExportUrl(s.name, s.source === "project" ? projectId : null)}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="builtin-skills" className="flex flex-col gap-3">
        <h2 id="builtin-skills" className="text-sm font-medium">
          Built-in skills <span className="font-normal text-muted-foreground">(one per playbook, read-only)</span>
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {builtin.map((s) => (
            <li key={s.name} className="rounded-lg border p-3 text-sm">
              <p className="font-mono">{s.command}</p>
              <p className="text-xs text-muted-foreground">{s.description}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SkillRow({
  skill,
  onToggle,
  onEdit,
  onTry,
  onDelete,
  exportUrl,
}: {
  skill: Skill;
  onToggle: (flags: { enabled?: boolean; auto_use?: boolean }) => void;
  onEdit: () => void;
  onTry: () => void;
  onDelete: () => void;
  exportUrl: string;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
          {skill.title}
          <span className="font-mono text-sm font-normal text-muted-foreground">{skill.command}</span>
          <Badge variant="outline">{skill.intent_label}</Badge>
          {skill.source === "project" && <Badge variant="secondary">this project</Badge>}
          {skill.languages.map((l) => (
            <Badge key={l} variant="secondary">
              {LANGUAGES.find((x) => x.id === l)?.label ?? l}
            </Badge>
          ))}
          {!skill.enabled && <Badge variant="outline">disabled</Badge>}
        </CardTitle>
        <CardDescription>{skill.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={skill.enabled} onCheckedChange={(v) => onToggle({ enabled: Boolean(v) })} />
          Enabled
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={skill.auto_use}
            disabled={!skill.enabled}
            onCheckedChange={(v) => onToggle({ auto_use: Boolean(v) })}
          />
          Use automatically
        </label>
        <span className="text-xs text-muted-foreground">Tools: {skill.allowed_tools.join(", ") || "none"}</span>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={onTry}>
            <FlaskConical aria-hidden="true" />
            Try
          </Button>
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Pencil aria-hidden="true" />
            Edit
          </Button>
          <a
            href={exportUrl}
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-sm hover:bg-muted"
            download={`${skill.name}.zip`}
          >
            <Download className="size-3.5" aria-hidden="true" />
            Export
          </a>
          <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Delete ${skill.command}`}>
            <Trash2 aria-hidden="true" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function SkillEditor({
  skill,
  projectId,
  playbooks,
  onCancel,
  onSaved,
}: {
  skill: Skill | null;
  projectId: string | null;
  playbooks: { value: string; label: string; hint?: string }[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<"form" | "markdown">(skill ? "markdown" : "form");
  const [form, setForm] = useState<FormState>(skill ? fromSkill(skill) : EMPTY_FORM);
  const [markdown, setMarkdown] = useState(skill?.markdown ?? "");
  const [scope, setScope] = useState<"global" | "project">(skill?.source === "project" ? "project" : "global");
  const [tools, setTools] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));
  const scopeValue = scope === "project" && projectId ? `project:${projectId}` : "global";

  useEffect(() => {
    getSkillTemplate()
      .then((t) => {
        setTools(t.tools);
        setMarkdown((m) => m || t.markdown);
      })
      .catch(() => setTools([]));
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    const text = mode === "form" ? toMarkdown(form, scopeValue) : markdown;
    const pid = scope === "project" ? projectId : null;
    try {
      if (skill) await replaceSkill(skill.name, text, pid);
      else await createSkill(text, pid);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{skill ? `Edit ${skill.command}` : "New skill"}</CardTitle>
        <CardDescription>
          The description is what Codewright matches requests against, so say what the skill does and when to use it.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Editor">
          {(["form", "markdown"] as const).map((m) => (
            <Button
              key={m}
              size="sm"
              role="tab"
              aria-selected={mode === m}
              variant={mode === m ? "secondary" : "ghost"}
              onClick={() => {
                if (m === "markdown" && mode === "form") setMarkdown(toMarkdown(form, scopeValue));
                setMode(m);
              }}
            >
              {m === "form" ? "Form" : "Markdown (SKILL.md)"}
            </Button>
          ))}
          {projectId && (
            <label className="ml-auto flex items-center gap-2 text-sm">
              <Checkbox checked={scope === "project"} onCheckedChange={(v) => setScope(v ? "project" : "global")} />
              Only for the selected project
            </label>
          )}
        </div>
        {mode === "form" ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="skill-title">Title</Label>
              <Input
                id="skill-title"
                value={form.title}
                placeholder="Go error review"
                onChange={(e) =>
                  set({ title: e.target.value, ...(skill ? {} : { name: slug(e.target.value), command: "" }) })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="skill-command">Command</Label>
              <Input
                id="skill-command"
                value={form.command || `/${slug(form.name || form.title)}`}
                onChange={(e) => set({ command: e.target.value })}
                className="font-mono"
              />
            </div>
            <div className="grid gap-1.5 md:col-span-2">
              <Label htmlFor="skill-description">Description (what it does, when to use it)</Label>
              <Input
                id="skill-description"
                value={form.description}
                placeholder="Review Go code for ignored and unwrapped errors. Use when the user asks for a Go error check."
                onChange={(e) => set({ description: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="skill-playbook">Runs as</Label>
              <FormSelect
                id="skill-playbook"
                value={form.playbook}
                options={playbooks}
                onChange={(v) => set({ playbook: v })}
              />
            </div>
            <fieldset className="grid gap-1.5">
              <legend className="pb-1.5 text-sm font-medium">Languages (none = all)</legend>
              <div className="flex flex-wrap gap-3">
                {LANGUAGES.map((l) => (
                  <label key={l.id} className="flex items-center gap-1.5 text-sm">
                    <Checkbox
                      checked={form.languages.includes(l.id)}
                      onCheckedChange={(v) =>
                        set({
                          languages: v ? [...form.languages, l.id] : form.languages.filter((x) => x !== l.id),
                        })
                      }
                    />
                    {l.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="grid gap-1.5 md:col-span-2">
              <legend className="pb-1.5 text-sm font-medium">Allowed tools</legend>
              <div className="flex flex-wrap gap-3">
                {tools.map((t) => (
                  <label key={t} className="flex items-center gap-1.5 font-mono text-xs">
                    <Checkbox
                      checked={form.tools.includes(t)}
                      onCheckedChange={(v) =>
                        set({ tools: v ? [...form.tools, t] : form.tools.filter((x) => x !== t) })
                      }
                    />
                    {t}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-1.5 md:col-span-2">
              <Label htmlFor="skill-instructions">Instructions (Markdown)</Label>
              <Textarea
                id="skill-instructions"
                value={form.instructions}
                rows={10}
                className="font-mono text-xs"
                onChange={(e) => set({ instructions: e.target.value })}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.autoUse} onCheckedChange={(v) => set({ autoUse: Boolean(v) })} />
              Use automatically when a request matches
            </label>
          </div>
        ) : (
          <Textarea
            value={markdown}
            onChange={(e) => setMarkdown(e.target.value)}
            rows={22}
            className="font-mono text-xs"
            aria-label="SKILL.md"
          />
        )}
        {error && (
          <p role="alert" className="text-sm whitespace-pre-line text-destructive">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Button onClick={() => void save()} disabled={saving}>
            {skill ? "Save changes" : "Create skill"}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function TryPanel({
  skill,
  projects,
  projectId,
  onCancel,
  onStarted,
}: {
  skill: Skill;
  projects: Project[];
  projectId: string | null;
  onCancel: () => void;
  onStarted: (conversationId: string) => void;
}) {
  const [input, setInput] = useState("");
  const [project, setProject] = useState(projectId ?? "");
  const [error, setError] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Try <span className="font-mono">{skill.command}</span>
        </CardTitle>
        <CardDescription>
          Runs the skill in a new chat on a sample input{skill.enabled ? "" : ", even though it is disabled"}.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="try-input">Sample input</Label>
          <Input
            id="try-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="internal/payment"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="try-project">Project</Label>
          <FormSelect
            id="try-project"
            value={project || "none"}
            options={[{ value: "none", label: "No project" }, ...projects.map((p) => ({ value: p.id, label: p.name }))]}
            onChange={(v) => setProject(v === "none" ? "" : v)}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            onClick={() =>
              void trySkill(skill.name, input, project || null)
                .then((r) => onStarted(r.conversation_id))
                .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
            }
          >
            <FlaskConical aria-hidden="true" />
            Run it
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ImportPanel({ projectId, onDone }: { projectId: string | null; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [gitUrl, setGitUrl] = useState("");
  const [folder, setFolder] = useState("");
  const [folders, setFolders] = useState<string[]>([]);
  const [results, setResults] = useState<ImportResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getConnectors()
      .then((c) => setFolders(c.local_folders))
      .catch(() => setFolders([]));
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const res = await importSkills(file ? { file } : gitUrl ? { gitUrl } : folder ? { folder } : {}, projectId);
      setResults(res.results);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Import skills</CardTitle>
        <CardDescription>
          From a ZIP, a GitHub repository or a folder in the shared local folder. Each skill is checked (format,
          secrets) and saved <strong>disabled</strong>: read its instructions and tools, then enable it.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="grid gap-1.5">
            <Label htmlFor="import-zip">ZIP file</Label>
            <Input id="import-zip" type="file" accept=".zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="import-git">Git repository URL</Label>
            <Input
              id="import-git"
              value={gitUrl}
              onChange={(e) => setGitUrl(e.target.value)}
              placeholder="https://github.com/team/skills"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="import-folder">Shared folder</Label>
            <FormSelect
              id="import-folder"
              value={folder || "none"}
              options={[{ value: "none", label: "None" }, ...folders.map((f) => ({ value: f, label: f }))]}
              onChange={(v) => setFolder(v === "none" ? "" : v)}
            />
          </div>
        </div>
        {error && (
          <p role="alert" className="text-sm whitespace-pre-line text-destructive">
            {error}
          </p>
        )}
        <div>
          <Button onClick={() => void run()} disabled={busy || (!file && !gitUrl && !folder)}>
            <Upload aria-hidden="true" />
            Import
          </Button>
        </div>
        {results && (
          <ul className="flex flex-col gap-2" aria-label="Import results">
            {results.map((r) => (
              <li key={r.folder} className="rounded-lg border p-3 text-sm">
                {r.ok ? (
                  <>
                    <p className="font-medium">
                      <span className="font-mono">{r.command}</span> imported (disabled)
                      {r.replaced && <span className="text-muted-foreground">, replaced the old version</span>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {r.description} · Tools: {r.allowed_tools?.join(", ") || "none"} · Runs as {r.playbook}
                    </p>
                    <details className="mt-1 text-xs">
                      <summary className="cursor-pointer text-muted-foreground">Instructions</summary>
                      <Markdown>{r.instructions_preview ?? ""}</Markdown>
                    </details>
                  </>
                ) : (
                  <>
                    <p className="font-medium text-destructive">{r.folder}: not imported</p>
                    <ul className="list-disc pl-5 text-xs">
                      {r.problems?.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
