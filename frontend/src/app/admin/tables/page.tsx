"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button, Card, ErrorBox, Field, PageHeader, Spinner, inputCls } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { COLUMN_TYPES, type ColumnType, type ImportColumn, type ImportResult, type ImportedTableInfo, type PreviewResponse } from "@/lib/types";

const IDENT = /^[a-z][a-z0-9_]{0,62}$/;

interface Draft extends ImportColumn { reason: string | null; samples: string[]; nulls: number }

export default function TablesPage() {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [tableName, setTableName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<"create" | "replace">("create");
  const [cols, setCols] = useState<Draft[]>([]);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [imported, setImported] = useState<ImportedTableInfo[] | null>(null);
  const [disabled, setDisabled] = useState(false);

  const loadImported = useCallback(() => {
    api.importedTables().then(setImported).catch((e: ApiError) => {
      if (e.status === 403) setDisabled(true); else setError(e.message);
    });
  }, []);
  useEffect(loadImported, [loadImported]);

  function reset() {
    setFile(null); setPreview(null); setCols([]); setError(null); setMode("create");
    if (fileInput.current) fileInput.current.value = "";
  }

  async function onPick(f: File | null) {
    reset(); setResult(null);
    if (!f) return;
    setFile(f); setBusy("preview");
    try {
      const p = await api.previewCsv(f);
      setPreview(p); setTableName(p.suggested_table_name); setDescription(p.suggested_table_description);
      setMode(p.name_conflict && p.can_replace ? "replace" : "create");
      setCols(p.columns.map((c) => ({ original_name: c.original_name, name: c.name, type: c.type, description: c.suggested_description,
        sensitive: c.suggested_sensitive, reason: c.sensitive_reason, samples: c.sample_values, nulls: c.null_count })));
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setDisabled(true);
      setError(e instanceof ApiError ? e.message : "Could not read the file."); setFile(null);
    } finally { setBusy(null); }
  }

  const patch = (i: number, p: Partial<Draft>) => setCols((cs) => cs.map((c, j) => (j === i ? { ...c, ...p } : c)));

  const nameOk = IDENT.test(tableName);
  const colNames = cols.map((c) => c.name);
  const colErrors = cols.map((c) => (!IDENT.test(c.name) ? "lowercase letters, digits, _" : colNames.filter((n) => n === c.name).length > 1 ? "duplicate" : ""));
  const conflictBlocks = !!preview && preview.name_conflict && tableName === preview.suggested_table_name && !(preview.can_replace && mode === "replace");
  const canImport = !!file && !!preview && nameOk && colErrors.every((e) => !e) && !conflictBlocks && busy === null;

  async function doImport() {
    if (!file || !canImport) return;
    setBusy("import"); setError(null);
    try {
      const res = await api.importCsv(file, {
        table_name: tableName, description, mode: preview!.name_conflict && tableName === preview!.suggested_table_name ? mode : "create",
        columns: cols.map(({ original_name, name, type, description: d, sensitive }) => ({ original_name, name, type, description: d, sensitive })),
      });
      setResult(res); toast.push("success", `Imported ${res.rows_imported.toLocaleString()} rows into “${res.table.name}”`);
      reset(); loadImported();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Import failed";
      setError(msg); toast.push("error", "Import failed — see the message below");
    } finally { setBusy(null); }
  }

  async function remove(name: string) {
    if (!confirm(`Delete the imported table “${name}” and all its data? This cannot be undone.`)) return;
    try { await api.deleteImported(name); toast.push("success", `Deleted ${name}`); loadImported(); }
    catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Delete failed"); }
  }

  if (disabled) return <ErrorBox message="Table import is disabled on this server (ALLOW_TABLE_IMPORT=false)." />;

  return (
    <>
      <PageHeader title="Add table from CSV"
        subtitle="Upload a CSV file, review the detected column types and likely personal-data columns, then import it. Once imported you can ask questions about it right away. Original tables are never modified." />

      <Card className="mb-6">
        <Field label="CSV file" hint="Comma, semicolon, tab or pipe separated, with a header row. Up to 10 MB and 100,000 rows. Dates should be YYYY-MM-DD.">
          <input ref={fileInput} type="file" accept=".csv,.tsv,.txt,text/csv" disabled={busy !== null}
            onChange={(e) => onPick(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-indigo-600 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-indigo-700" />
        </Field>
        {busy === "preview" && <div className="mt-3"><Spinner label="Reading and analysing the file…" /></div>}
      </Card>

      {error && <div className="mb-4"><ErrorBox message={error} /></div>}

      {result && (
        <Card className="mb-6 border-emerald-200 bg-emerald-50">
          <p className="font-medium text-emerald-900">✅ {result.replaced ? "Replaced" : "Created"} table <code>{result.table.name}</code> with {result.rows_imported.toLocaleString()} rows and {result.table.columns.length} columns.</p>
          <div className="mt-2 flex flex-wrap gap-3 text-sm">
            <Link href="/" className="font-medium text-indigo-700 underline">Ask questions about it →</Link>
            <Link href="/admin/schema" className="font-medium text-indigo-700 underline">Review descriptions in Schema →</Link>
            <Link href="/admin/examples" className="font-medium text-indigo-700 underline">Add example questions →</Link>
          </div>
        </Card>
      )}

      {preview && (
        <Card className="mb-6 space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold">{preview.filename} · {preview.row_count.toLocaleString()} rows · {preview.columns.length} columns</h2>
            <span className="text-xs text-slate-500">delimiter “{preview.delimiter}” · {preview.encoding}</span>
          </div>

          {preview.warnings.map((w) => <p key={w} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">⚠ {w}</p>)}

          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Table name" hint="lowercase letters, digits and underscores">
              <input className={`${inputCls} ${nameOk ? "" : "border-red-400"}`} value={tableName} onChange={(e) => setTableName(e.target.value)} />
            </Field>
            <div className="md:col-span-2"><Field label="Table description">
              <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
            </Field></div>
          </div>

          {preview.name_conflict && tableName === preview.suggested_table_name && (
            preview.can_replace ? (
              <label className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <input type="checkbox" checked={mode === "replace"} onChange={(e) => setMode(e.target.checked ? "replace" : "create")} />
                A table named <code>{tableName}</code> was imported before. Tick to replace it (its data is overwritten).
              </label>
            ) : (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                <code>{tableName}</code> is an original table and cannot be overwritten. Choose a different table name.
              </p>
            )
          )}

          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr><th className="px-3 py-2">File column</th><th className="px-3 py-2">Column name</th><th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Description</th><th className="px-3 py-2 text-center">Sensitive</th></tr>
              </thead>
              <tbody>
                {cols.map((c, i) => (
                  <tr key={c.original_name} className="border-t border-slate-100 align-top">
                    <td className="px-3 py-2"><div className="font-medium">{c.original_name}</div>
                      <div className="max-w-[14rem] truncate text-xs text-slate-500" title={c.samples.join(", ")}>{c.samples.join(", ") || "—"}</div>
                      {c.nulls > 0 && <div className="text-xs text-slate-400">{c.nulls} empty</div>}</td>
                    <td className="px-3 py-2"><input className={`${inputCls} font-mono text-xs ${colErrors[i] ? "border-red-400" : ""}`} value={c.name}
                      onChange={(e) => patch(i, { name: e.target.value })} aria-label={`Name for ${c.original_name}`} />
                      {colErrors[i] && <span className="text-xs text-red-600">{colErrors[i]}</span>}</td>
                    <td className="px-3 py-2"><select className={inputCls} value={c.type} onChange={(e) => patch(i, { type: e.target.value as ColumnType })} aria-label={`Type for ${c.original_name}`}>
                      {COLUMN_TYPES.map((t) => <option key={t}>{t}</option>)}</select></td>
                    <td className="px-3 py-2"><input className={inputCls} value={c.description} maxLength={500} onChange={(e) => patch(i, { description: e.target.value })} aria-label={`Description for ${c.original_name}`} /></td>
                    <td className="px-3 py-2 text-center">
                      <input type="checkbox" className="h-4 w-4 accent-red-600" checked={c.sensitive} onChange={(e) => patch(i, { sensitive: e.target.checked })} aria-label={`Sensitive: ${c.original_name}`} />
                      {c.reason && <div className="mt-1 max-w-[10rem] text-xs text-red-700">Suggested: {c.reason}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <details className="rounded-lg border border-slate-200 bg-slate-50">
            <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-slate-700">Preview the first rows</summary>
            <div className="overflow-x-auto px-3 pb-3">
              <table className="min-w-full text-xs"><thead><tr>{preview.columns.map((c) => <th key={c.original_name} className="px-2 py-1 text-left font-medium">{c.original_name}</th>)}</tr></thead>
                <tbody>{preview.sample_rows.map((r, i) => <tr key={i} className="border-t border-slate-200">{r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1">{v ?? <span className="text-slate-400">—</span>}</td>)}</tr>)}</tbody></table>
            </div>
          </details>

          <p className="text-xs text-slate-500">Sensitive columns are removed from every prompt sent to the AI, from query validation and from results. Tick any column holding personal data.</p>
          <div className="flex gap-2">
            <Button onClick={doImport} disabled={!canImport}>{busy === "import" ? "Importing…" : `Import ${preview.row_count.toLocaleString()} rows`}</Button>
            <Button variant="ghost" onClick={reset} disabled={busy !== null}>Cancel</Button>
          </div>
        </Card>
      )}

      <h2 className="mb-2 text-sm font-semibold">Imported tables</h2>
      {!imported && !error && <Spinner />}
      {imported && imported.length === 0 && <p className="text-sm text-slate-500">Nothing imported yet.</p>}
      <div className="space-y-2">
        {imported?.map((t) => (
          <Card key={t.table_name} className="flex flex-wrap items-center justify-between gap-3 !p-3">
            <div><span className="font-mono font-semibold">{t.table_name}</span>
              <span className="ml-3 text-xs text-slate-500">{t.row_count.toLocaleString()} rows · from {t.source_filename || "unknown file"} · {t.created_at.slice(0, 16).replace("T", " ")} UTC</span></div>
            <Button variant="danger" onClick={() => remove(t.table_name)}>Delete</Button>
          </Card>
        ))}
      </div>
    </>
  );
}
