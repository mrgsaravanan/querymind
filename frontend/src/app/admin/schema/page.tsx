"use client";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button, Card, ErrorBox, PageHeader, Spinner, inputCls } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ColumnInfo, TableInfo } from "@/lib/types";

function ColumnRow({ table, col, onSaved }: { table: string; col: ColumnInfo; onSaved: (t: TableInfo[]) => void }) {
  const toast = useToast();
  const [desc, setDesc] = useState(col.description);
  const [saving, setSaving] = useState(false);
  useEffect(() => setDesc(col.description), [col.description]);

  async function save(patch: { description?: string; sensitive?: boolean }, okMsg: string) {
    setSaving(true);
    try {
      onSaved(await api.updateSchema({ columns: [{ table, column: col.name, ...patch }] }));
      toast.push("success", okMsg);
    } catch (e) {
      toast.push("error", e instanceof ApiError ? e.message : "Save failed");
      setDesc(col.description);
    } finally { setSaving(false); }
  }

  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="px-3 py-2 font-mono text-xs">
        {col.name}
        {col.is_primary_key && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">PK</span>}
        {col.foreign_key && <div className="text-[10px] text-slate-500">→ {col.foreign_key}</div>}
      </td>
      <td className="px-3 py-2 text-xs text-slate-500">{col.type}</td>
      <td className="px-3 py-2">
        <div className="flex gap-2">
          <input value={desc} onChange={(e) => setDesc(e.target.value)} aria-label={`Description of ${table}.${col.name}`} className={inputCls}
            onKeyDown={(e) => e.key === "Enter" && desc !== col.description && save({ description: desc }, `Saved ${table}.${col.name}`)} />
          <Button variant="ghost" disabled={saving || desc === col.description} onClick={() => save({ description: desc }, `Saved ${table}.${col.name}`)}>Save</Button>
        </div>
      </td>
      <td className="px-3 py-2 text-center">
        <input type="checkbox" checked={col.sensitive} disabled={saving} aria-label={`Sensitive: ${table}.${col.name}`}
          className="h-4 w-4 accent-red-600"
          onChange={(e) => save({ sensitive: e.target.checked }, `${table}.${col.name} marked ${e.target.checked ? "sensitive" : "not sensitive"}`)} />
      </td>
    </tr>
  );
}

function TableCard({ t, onSaved }: { t: TableInfo; onSaved: (t: TableInfo[]) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [desc, setDesc] = useState(t.description);
  useEffect(() => setDesc(t.description), [t.description]);
  const nSens = t.columns.filter((c) => c.sensitive).length;

  async function saveTable() {
    try { onSaved(await api.updateSchema({ tables: [{ table: t.name, description: desc }] })); toast.push("success", `Saved table ${t.name}`); }
    catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Save failed"); }
  }

  return (
    <Card className="!p-0">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <span><span className="font-mono font-semibold">{t.name}</span>
          <span className="ml-3 text-xs text-slate-500">{t.columns.length} columns{nSens > 0 && ` · ${nSens} sensitive`}</span></span>
        <span className="text-slate-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="border-t border-slate-200 px-4 py-3">
          <div className="mb-3 flex gap-2">
            <input value={desc} onChange={(e) => setDesc(e.target.value)} aria-label={`Description of table ${t.name}`} className={inputCls} placeholder="Table description" />
            <Button variant="ghost" disabled={desc === t.description} onClick={saveTable}>Save</Button>
          </div>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase text-slate-500">
              <th className="px-3 py-1">Column</th><th className="px-3 py-1">Type</th><th className="px-3 py-1">Description</th><th className="px-3 py-1 text-center">Sensitive</th>
            </tr></thead>
            <tbody>{t.columns.map((c) => <ColumnRow key={c.name} table={t.name} col={c} onSaved={onSaved} />)}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function SchemaPage() {
  const [tables, setTables] = useState<TableInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { setError(null); api.schema().then(setTables).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);

  return (
    <>
      <PageHeader title="Schema Manager"
        subtitle="Describe tables and columns in business language (use “(also: synonym, …)” for aliases). Sensitive columns are removed from every LLM prompt, the linker, validation and results." />
      {error && <ErrorBox message={error} onRetry={load} />}
      {!tables && !error && <Spinner />}
      <div className="space-y-3">{tables?.map((t) => <TableCard key={t.name} t={t} onSaved={setTables} />)}</div>
    </>
  );
}
