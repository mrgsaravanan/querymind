/** Admin token kept in sessionStorage (cleared when the tab closes). Storage can be unavailable (private mode), so never throw. */
const KEY = "querymind_admin_token";

export function getAdminToken(): string {
  try { return sessionStorage.getItem(KEY) ?? ""; } catch { return ""; }
}
export function setAdminToken(token: string): void {
  try { sessionStorage.setItem(KEY, token); } catch { /* ignore */ }
}
export function clearAdminToken(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
}
