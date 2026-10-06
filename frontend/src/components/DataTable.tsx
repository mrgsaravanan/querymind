"use client";
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";

type Row = Record<string, unknown>;

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}

/** Sortable result table (click a header to cycle asc / desc / none). */
export default function DataTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const data = useMemo<Row[]>(() => rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i]]))), [columns, rows]);
  const defs = useMemo<ColumnDef<Row>[]>(
    () => columns.map((c) => ({
      accessorKey: c, header: c,
      cell: (ctx) => fmt(ctx.getValue()),
      sortingFn: (a, b, id) => {
        const x = a.getValue(id), y = b.getValue(id);
        if (x == null) return y == null ? 0 : -1;
        if (y == null) return 1;
        return typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      },
    })), [columns]);
  const numeric = useMemo(() => new Set(columns.filter((c, i) => rows.some((r) => r[i] != null) && typeof rows.find((r) => r[i] != null)![i] === "number")), [columns, rows]);
  const table = useReactTable({ data, columns: defs, state: { sorting }, onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });

  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 bg-slate-50">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const dir = h.column.getIsSorted();
                return (
                  <th key={h.id} onClick={h.column.getToggleSortingHandler()} aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}
                    className={`cursor-pointer select-none whitespace-nowrap border-b border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-100 ${numeric.has(h.column.id) ? "text-right" : "text-left"}`}>
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    <span className="ml-1 text-slate-400">{dir === "asc" ? "▲" : dir === "desc" ? "▼" : "↕"}</span>
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((r) => (
            <tr key={r.id} className="odd:bg-white even:bg-slate-50/50">
              {r.getVisibleCells().map((c) => (
                <td key={c.id} className={`whitespace-nowrap border-b border-slate-100 px-3 py-1.5 ${typeof c.getValue() === "number" ? "text-right tabular-nums" : ""}`}>
                  {flexRender(c.column.columnDef.cell, c.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
