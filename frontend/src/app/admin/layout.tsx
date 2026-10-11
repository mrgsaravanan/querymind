"use client";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Button, Card, ErrorBox, Spinner, inputCls } from "@/components/ui";
import { API_BASE } from "@/lib/api";
import { clearAdminToken, getAdminToken, setAdminToken } from "@/lib/adminToken";

type State = "checking" | "ok" | "locked" | "unreachable";

/** Wraps every /admin page. If the server has ADMIN_TOKEN set, asks for it once per browser session. */
export default function AdminLayout({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>("checking");
  const [token, setToken] = useState("");
  const [wrong, setWrong] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  const check = useCallback(async (candidate: string) => {
    setState("checking");
    try {
      const res = await fetch(`${API_BASE}/admin/config`, { headers: candidate ? { "X-Admin-Token": candidate } : {}, cache: "no-store" });
      if (res.status === 401) { setState("locked"); return false; }
      setState(res.ok ? "ok" : "unreachable");
      return res.ok;
    } catch { setState("unreachable"); return false; }
  }, []);

  useEffect(() => { const t = getAdminToken(); setHasToken(!!t); check(t); }, [check]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await check(token.trim());
    setWrong(!ok);
    if (ok) { setAdminToken(token.trim()); setHasToken(true); setToken(""); }
  }

  if (state === "checking") return <Spinner label="Checking admin access…" />;
  if (state === "unreachable") return <ErrorBox message={`Cannot reach the API at ${API_BASE}. Is the backend running?`} onRetry={() => check(getAdminToken())} />;
  if (state === "locked")
    return (
      <Card className="mx-auto mt-10 max-w-md">
        <h1 className="text-lg font-semibold">Admin sign-in</h1>
        <p className="mt-1 text-sm text-slate-600">Enter the admin token to manage schema, examples, guardrails and models. Everyone can still use the Ask page.</p>
        <form onSubmit={submit} className="mt-4 space-y-3">
          <input type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} className={`${inputCls} ${wrong ? "border-red-400" : ""}`}
            placeholder="Admin token" aria-label="Admin token" autoFocus />
          {wrong && <p role="alert" className="text-sm text-red-700">That token was not accepted.</p>}
          <Button type="submit" disabled={!token.trim()}>Unlock admin</Button>
        </form>
      </Card>
    );
  return (
    <>
      {hasToken && (
        <div className="mb-4 flex justify-end">
          <button onClick={() => { clearAdminToken(); setHasToken(false); check(""); }} className="text-xs text-slate-500 underline hover:text-slate-700">Lock admin</button>
        </div>
      )}
      {children}
    </>
  );
}
