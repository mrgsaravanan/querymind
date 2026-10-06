"use client";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/** Chart-able = exactly two columns (label + number), at least two rows. Time-like labels get a line, others a bar. */
export function chartSpec(columns: string[], rows: unknown[][]): { kind: "bar" | "line"; data: { label: string; value: number }[]; xName: string; yName: string } | null {
  if (columns.length !== 2 || rows.length < 2) return null;
  const numeric = rows.every((r) => typeof r[1] === "number");
  const labelNumeric = rows.every((r) => typeof r[0] === "number");
  if (!numeric || labelNumeric) return null;
  const data = rows.slice(0, 50).map((r) => ({ label: String(r[0]), value: r[1] as number }));
  const timeLike = data.every((d) => /^\d{4}(-\d{2})?(-\d{2})?$/.test(d.label));
  return { kind: timeLike ? "line" : "bar", data, xName: columns[0], yName: columns[1] };
}

export default function ResultChart({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const spec = chartSpec(columns, rows);
  if (!spec) return null;
  const common = { data: spec.data, margin: { top: 8, right: 8, left: 0, bottom: 8 } };
  return (
    <div className="h-64 w-full rounded-lg border border-slate-200 bg-white p-2" aria-label={`${spec.kind} chart of ${spec.yName} by ${spec.xName}`}>
      <ResponsiveContainer>
        {spec.kind === "line" ? (
          <LineChart {...common}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" fontSize={11} /><YAxis fontSize={11} width={60} />
            <Tooltip /><Line type="monotone" dataKey="value" name={spec.yName} stroke="#4f46e5" strokeWidth={2} dot={false} /></LineChart>
        ) : (
          <BarChart {...common}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" fontSize={11} interval={0} angle={spec.data.length > 6 ? -30 : 0} textAnchor={spec.data.length > 6 ? "end" : "middle"} height={spec.data.length > 6 ? 60 : 30} />
            <YAxis fontSize={11} width={60} /><Tooltip /><Bar dataKey="value" name={spec.yName} fill="#4f46e5" radius={[3, 3, 0, 0]} /></BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
