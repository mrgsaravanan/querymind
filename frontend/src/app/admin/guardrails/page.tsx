"use client";
import { useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button, Card, ErrorBox, Field, PageHeader, Spinner, inputCls } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { GuardrailConfig } from "@/lib/types";

const OPS: { key: keyof GuardrailConfig; label: string }[] = [
  { key: "allow_select", label: "SELECT" }, { key: "allow_insert", label: "INSERT" }, { key: "allow_update", label: "UPDATE" },
  { key: "allow_delete", label: "DELETE" }, { key: "allow_drop", label: "DROP" }, { key: "allow_truncate", label: "TRUNCATE" },
  { key: "allow_alter", label: "ALTER" }, { key: "allow_create", label: "CREATE" },
];
const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export default function GuardrailsPage() {
  const toast = useToast();
  const [cfg, setCfg] = useState<GuardrailConfig | null>(null);
  const [prefixes, setPrefixes] = useState("");
  const [schemas, setSchemas] = useState("");
  const [maxRows, setMaxRows] = useState("100");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = () => api.guardrails().then((g) => {
    setCfg(g); setPrefixes(g.allowed_table_prefixes.join(", ")); setSchemas(g.allowed_schemas.join(", ")); setMaxRows(String(g.max_rows));
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const rows = Number(maxRows);
  const rowsValid = Number.isInteger(rows) && rows >= 1 && rows <= 100000;

  async function save() {
    if (!cfg || !rowsValid) return;
    setSaving(true);
    try {
      const saved = await api.saveGuardrails({ ...cfg, max_rows: rows, allowed_table_prefixes: split(prefixes), allowed_schemas: split(schemas) });
      setCfg(saved); toast.push("success", "Guardrails saved — active on the next query");
    } catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Save failed"); }
    finally { setSaving(false); }
  }

  if (error) return <ErrorBox message={error} onRetry={() => { setError(null); load(); }} />;
  if (!cfg) return <Spinner />;
  return (
    <>
      <PageHeader title="Guardrails Config"
        subtitle="Choose which SQL operations the validator will accept, cap returned rows, and restrict which tables can be queried." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-1 text-sm font-semibold">Allowed SQL operations</h2>
          <p className="mb-3 text-xs text-slate-500">Everything except SELECT is off by default. Even if you enable a write operation here, the database connection is read-only, so writes still fail.</p>
          <div className="grid grid-cols-2 gap-2">
            {OPS.map((o) => (
              <label key={o.key} className={`flex cursor-pointer items-center justify-between rounded-lg border px-3 py-2 text-sm ${cfg[o.key] ? (o.key === "allow_select" ? "border-emerald-300 bg-emerald-50" : "border-red-300 bg-red-50") : "border-slate-200"}`}>
                <span className="font-mono">{o.label}</span>
                <input type="checkbox" role="switch" className="h-4 w-4" checked={cfg[o.key] as boolean} onChange={(e) => setCfg({ ...cfg, [o.key]: e.target.checked })} />
              </label>
            ))}
          </div>
        </Card>
        <Card className="space-y-4">
          <Field label="Max rows returned" hint="LIMIT is appended if missing and clamped if larger. 1 – 100,000.">
            <input type="number" min={1} max={100000} className={`${inputCls} ${rowsValid ? "" : "border-red-400"}`} value={maxRows} onChange={(e) => setMaxRows(e.target.value)} />
            {!rowsValid && <span className="text-xs text-red-600">Enter a whole number between 1 and 100000.</span>}
          </Field>
          <Field label="Allowed table prefixes" hint="Comma-separated. Empty = all tables. Example: order, customer">
            <input className={inputCls} value={prefixes} onChange={(e) => setPrefixes(e.target.value)} placeholder="(all tables)" />
          </Field>
          <Field label="Allowed schemas" hint="Comma-separated. SQLite uses “main”.">
            <input className={inputCls} value={schemas} onChange={(e) => setSchemas(e.target.value)} />
          </Field>
          <Button onClick={save} disabled={saving || !rowsValid}>{saving ? "Saving…" : "Save guardrails"}</Button>
        </Card>
      </div>
    </>
  );
}
