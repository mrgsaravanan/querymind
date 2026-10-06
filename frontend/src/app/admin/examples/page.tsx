"use client";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button, Card, ErrorBox, Field, PageHeader, Spinner, inputCls } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { QUERY_TYPES, type ExampleHit, type ExampleRecord, type QueryType } from "@/lib/types";

const empty = { question: "", sql: "", query_type: "SELECT_SIMPLE" as QueryType | null };

function TypeBadge({ t }: { t: QueryType | null }) {
  return <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">{t ?? "UNLABELED"}</span>;
}

export default function ExamplesPage() {
  const toast = useToast();
  const [items, setItems] = useState<ExampleRecord[] | null>(null);
  const [hits, setHits] = useState<ExampleHit[] | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => { setError(null); api.examples().then(setItems).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);

  const valid = form.question.trim().length >= 3 && form.sql.trim().length >= 3;

  async function submit() {
    if (!valid) return;
    setSaving(true);
    try {
      if (editingId) await api.updateExample(editingId, form); else await api.createExample(form);
      toast.push("success", editingId ? "Example updated and re-indexed" : "Example added and indexed");
      setForm(empty); setEditingId(null); setHits(null); load();
    } catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Save failed"); }
    finally { setSaving(false); }
  }

  async function remove(id: number) {
    if (!confirm("Delete this example? It will also be removed from the vector index.")) return;
    try { await api.deleteExample(id); toast.push("success", "Example deleted"); setHits(null); load(); }
    catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Delete failed"); }
  }

  async function runSearch() {
    if (!search.trim()) { setHits(null); return; }
    try { setHits(await api.searchExamples(search.trim())); }
    catch (e) { toast.push("error", e instanceof ApiError ? e.message : "Search failed"); }
  }

  const shown: (ExampleRecord & { score?: number })[] = (hits ?? items ?? []).filter((x) => !typeFilter || x.query_type === typeFilter);

  return (
    <>
      <PageHeader title="Examples Manager" subtitle="Few-shot (question → SQL) pairs shown to the model. Edits re-embed the example; deletes remove it from the vector index. SQL is validated before saving." />
      <Card className="mb-6">
        <h2 className="mb-3 text-sm font-semibold">{editingId ? `Editing example #${editingId}` : "Add an example"}</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="md:col-span-2"><Field label="Question">
            <input className={inputCls} value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} placeholder="How many orders were cancelled last month?" />
          </Field></div>
          <Field label="Query type">
            <select className={inputCls} value={form.query_type ?? ""} onChange={(e) => setForm({ ...form, query_type: (e.target.value || null) as QueryType | null })}>
              {QUERY_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </Field>
          <div className="md:col-span-3"><Field label="SQL (SELECT only)">
            <textarea className={`${inputCls} h-28 font-mono text-xs`} value={form.sql} onChange={(e) => setForm({ ...form, sql: e.target.value })} />
          </Field></div>
        </div>
        <div className="mt-3 flex gap-2">
          <Button onClick={submit} disabled={!valid || saving}>{saving ? "Saving…" : editingId ? "Update example" : "Add example"}</Button>
          {editingId && <Button variant="ghost" onClick={() => { setEditingId(null); setForm(empty); }}>Cancel</Button>}
        </div>
        {!valid && (form.question || form.sql) && <p className="mt-2 text-xs text-amber-700">Question and SQL need at least 3 characters.</p>}
      </Card>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); runSearch(); }}>
          <input className={inputCls} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Semantic search, e.g. “money by country”" aria-label="Semantic search" />
          <Button type="submit" variant="ghost">Search</Button>
          {hits && <Button type="button" variant="ghost" onClick={() => { setHits(null); setSearch(""); }}>Clear</Button>}
        </form>
        <select className={`${inputCls} !w-52`} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Filter by type">
          <option value="">All types</option>{QUERY_TYPES.map((t) => <option key={t}>{t}</option>)}
        </select>
      </div>

      {error && <ErrorBox message={error} onRetry={load} />}
      {!items && !error && <Spinner />}
      <p className="mb-2 text-xs text-slate-500">{hits ? `${shown.length} semantic match(es)` : `${shown.length} example(s)`}</p>
      <div className="space-y-2">
        {shown.map((x) => (
          <Card key={x.id} className="!p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{x.question}</span><TypeBadge t={x.query_type} />
                  {"score" in x && x.score !== undefined && <span className="text-xs text-slate-500">similarity {(x.score * 100).toFixed(0)}%</span>}
                </div>
                <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-2 text-xs text-slate-100">{x.sql}</pre>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="ghost" onClick={() => { setEditingId(x.id); setForm({ question: x.question, sql: x.sql, query_type: x.query_type }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</Button>
                <Button variant="danger" onClick={() => remove(x.id)}>Delete</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
