import type {
  ImportConfig, ImportResult, ImportedTableInfo, PreviewResponse,
  ExampleHit, ExampleIn, ExampleRecord, GuardrailConfig, ModelConfig, QueryLogEntry, QueryResponse, TableInfo,
} from "./types";

import { getAdminToken } from "./adminToken";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

/** Turn FastAPI's various error shapes into one readable sentence. */
export function describeDetail(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        return `${loc ? loc + ": " : ""}${d?.msg ?? JSON.stringify(d)}`;
      })
      .join("; ");
  }
  if (typeof detail === "object") {
    const d = detail as { message?: string; errors?: string[] };
    if (d.message) return d.errors?.length ? `${d.message}: ${d.errors.join("; ")}` : d.message;
  }
  return JSON.stringify(detail);
}

/** Admin endpoints need the X-Admin-Token header when the server has ADMIN_TOKEN set. */
function adminHeaders(): Record<string, string> {
  const t = getAdminToken();
  return t ? { "X-Admin-Token": t } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...adminHeaders(), ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is the backend running?`);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = body?.error ? `${body.error}${body.detail ? ` — ${describeDetail(body.detail)}` : ""}` : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, body?.detail);
  }
  return body as T;
}

/** Multipart upload (the browser sets the boundary, so no JSON Content-Type header). */
async function upload<T>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method: "POST", body: form, headers: adminHeaders(), cache: "no-store" });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is the backend running?`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = body?.error ? `${body.error}${body.detail ? ` — ${describeDetail(body.detail)}` : ""}` : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, body?.detail);
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({ method, body: JSON.stringify(data) });

export async function runQuery(question: string, clarification?: string, targetDialect?: string): Promise<QueryResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/query`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, clarification: clarification ?? null, target_dialect: targetDialect ?? null }),
    });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is the backend running?`);
  }
  const body = await res.json().catch(() => null);
  if (res.status === 429) {
    const wait = res.headers.get("Retry-After");
    throw new ApiError(429, `${body?.error ?? "Too many requests."}${wait ? ` Try again in about ${Math.ceil(Number(wait) / 60)} minute(s).` : ""}`);
  }
  if (body && typeof body.status === "string") return body as QueryResponse; // includes 503 "error" outcomes
  throw new ApiError(res.status, body?.error ? `${body.error}: ${describeDetail(body.detail)}` : `Request failed (${res.status})`);
}

export const api = {
  schema: () => request<TableInfo[]>("/admin/schema"),
  updateSchema: (u: { tables?: { table: string; description: string }[]; columns?: { table: string; column: string; description?: string; sensitive?: boolean }[] }) =>
    request<TableInfo[]>("/admin/schema", json("PUT", u)),

  examples: () => request<ExampleRecord[]>("/admin/examples"),
  searchExamples: (q: string, k = 8) => request<ExampleHit[]>(`/admin/examples/search?q=${encodeURIComponent(q)}&k=${k}`),
  createExample: (e: ExampleIn) => request<ExampleRecord>("/admin/examples", json("POST", e)),
  updateExample: (id: number, e: ExampleIn) => request<ExampleRecord>(`/admin/examples/${id}`, json("PUT", e)),
  deleteExample: (id: number) => request<void>(`/admin/examples/${id}`, { method: "DELETE" }),

  logs: (p: Record<string, string>) => request<QueryLogEntry[]>(`/admin/logs?${new URLSearchParams(p)}`),
  /** Download the CSV through fetch so the admin token header can be sent (an <a href> cannot). */
  downloadLogsCsv: async (p: Record<string, string>) => {
    let res: Response;
    try { res = await fetch(`${API_BASE}/admin/logs/export?${new URLSearchParams({ format: "csv", ...p })}`, { headers: adminHeaders() }); }
    catch { throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is the backend running?`); }
    if (!res.ok) throw new ApiError(res.status, res.status === 401 ? "Admin token required or incorrect." : `Export failed (${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = "query_logs.csv"; document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  },

  guardrails: () => request<GuardrailConfig>("/admin/guardrails"),
  saveGuardrails: (g: GuardrailConfig) => request<GuardrailConfig>("/admin/guardrails", json("PUT", g)),

  previewCsv: (file: File) => { const f = new FormData(); f.append("file", file); return upload<PreviewResponse>("/admin/tables/preview", f); },
  importCsv: (file: File, config: ImportConfig) => {
    const f = new FormData(); f.append("file", file); f.append("config", JSON.stringify(config));
    return upload<ImportResult>("/admin/tables/import", f);
  },
  importedTables: () => request<ImportedTableInfo[]>("/admin/tables/imported"),
  deleteImported: (name: string) => request<void>(`/admin/tables/${encodeURIComponent(name)}`, { method: "DELETE" }),

  config: () => request<ModelConfig>("/admin/config"),
  saveConfig: (c: ModelConfig) => request<ModelConfig>("/admin/config", json("PUT", c)),
};
