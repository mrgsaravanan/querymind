"use client";
import { useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button, Card, ErrorBox, Field, PageHeader, Spinner, inputCls } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ModelConfig } from "@/lib/types";

const PROVIDERS = [
  { id: "claude_cli", label: "Claude subscription (CLI login, no API key)", model: "sonnet" },
  { id: "anthropic", label: "Anthropic API (API key)", model: "claude-sonnet-4-20250514" },
  { id: "openai", label: "OpenAI", model: "gpt-4o" },
  { id: "ollama", label: "Ollama (local)", model: "llama3.1" },
] as const;

export default function ModelPage() {
  const toast = useToast();
  const [cfg, setCfg] = useState<ModelConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const load = () => api.config().then(setCfg).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (error) return <ErrorBox message={error} onRetry={() => { setError(null); load(); }} />;
  if (!cfg) return <Spinner />;

  const tokensValid = Number.isInteger(cfg.max_tokens) && cfg.max_tokens >= 64 && cfg.max_tokens <= 8192;
  const valid = tokensValid && cfg.model.trim().length > 0;

  async function save() {
    if (!cfg || !valid) return;
    setSaving(true);
    try { setCfg(await api.saveConfig(cfg)); toast.push("success", "Model config saved — used from the next query"); }
    catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Save failed"); }
    finally { setSaving(false); }
  }

  return (
    <>
      <PageHeader title="Model Config" subtitle="Which LLM writes the SQL, how creative it may be, and which SQL dialect it targets. API keys are read from the server environment, never from this page." />
      <Card className="max-w-2xl space-y-5">
        <Field label="Provider">
          <select className={inputCls} value={cfg.provider}
            onChange={(e) => { const p = PROVIDERS.find((x) => x.id === e.target.value)!; setCfg({ ...cfg, provider: p.id, model: p.model }); }}>
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </Field>
        {cfg.provider === "claude_cli" && (
          <p className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
            Uses your Claude subscription through the <code>claude</code> CLI (run <code>claude login</code> once). Use a model alias such as
            <code> sonnet</code>. Temperature and token budget do not apply to this provider, and each call has a few seconds of CLI start-up overhead.
          </p>
        )}
        <Field label="Model name"><input className={inputCls} value={cfg.model} onChange={(e) => setCfg({ ...cfg, model: e.target.value })} /></Field>
        <Field label={`Temperature: ${cfg.temperature.toFixed(2)}`} hint="0 = deterministic (recommended for SQL). Higher = more varied.">
          <input type="range" min={0} max={1} step={0.05} className="w-full accent-indigo-600" value={cfg.temperature} onChange={(e) => setCfg({ ...cfg, temperature: Number(e.target.value) })} />
        </Field>
        <Field label="SQL dialect" hint="Generated SQL targets this dialect. The demo database is SQLite.">
          <select className={inputCls} value={cfg.dialect} onChange={(e) => setCfg({ ...cfg, dialect: e.target.value as ModelConfig["dialect"] })}>
            <option value="sqlite">SQLite</option><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option>
          </select>
        </Field>
        <Field label="Max token budget" hint="Upper bound on tokens per LLM response (64 – 8192).">
          <input type="number" min={64} max={8192} className={`${inputCls} ${tokensValid ? "" : "border-red-400"}`} value={cfg.max_tokens}
            onChange={(e) => setCfg({ ...cfg, max_tokens: Number(e.target.value) })} />
        </Field>
        <Button onClick={save} disabled={saving || !valid}>{saving ? "Saving…" : "Save model config"}</Button>
      </Card>
    </>
  );
}
