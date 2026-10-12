# Deploying QueryMind: Vercel (web UI) + Render (API)

> **Prefer one cheap server instead?** See **[HETZNER.md](HETZNER.md)**: everything (UI, API, HTTPS) on a single Hetzner VM with `docker compose`.

```
Browser ──▶ Vercel  (Next.js web UI, free/Pro)
              │  NEXT_PUBLIC_API_URL
              ▼
           Render   (Docker: FastAPI + SQLite + ChromaDB on a persistent disk)  ──▶ Anthropic API
```

**Why two hosts?** Vercel runs short-lived serverless functions with no persistent disk, but the API keeps `admin.db` (logs, edits, imported tables), the business database and the ChromaDB index on disk, and loads a ~0.9 GB embedding model. So the **web UI goes on Vercel** and the **API runs as a container on Render** (any Docker host with a disk works the same way).

**Your Claude subscription cannot be used for a public deployment**: the `claude` CLI login is personal. Public use needs an **Anthropic API key** (pay per question). Create one at console.anthropic.com and set a monthly spend limit there.

> Everything in the repo was verified locally (admin token, rate limits, CORS, entrypoint, frontend build). The Dockerfile and `render.yaml` could not be test-built on the machine they were written on (no Docker available), so watch the first Render build log.

## 0. Prerequisites
- The repo pushed to GitHub (this one is `mrgsaravanan/querymind`).
- Accounts: [Render](https://render.com), [Vercel](https://vercel.com), and an Anthropic API key.

## 1. Deploy the API on Render
1. Render dashboard → **New → Blueprint** → pick this repo. Render reads [`render.yaml`](render.yaml).
2. When prompted, enter **`ANTHROPIC_API_KEY`**. Leave `CORS_ORIGINS` empty for now.
3. Click **Apply**. The first build takes a few minutes (it bakes the embedding model into the image). On first boot the container builds the demo database on the persistent `/data` disk.
4. When it is live, open `https://<your-service>.onrender.com/health`: it should say `"status":"ok"`.
5. In the service's **Environment** tab, copy the generated **`ADMIN_TOKEN`**. This unlocks the Admin UI.

Plan: `standard` (2 GB RAM). The embedding model plus ChromaDB use about 0.9 GB, so the 512 MB tier will crash. To fit a smaller plan, set `EMBEDDING_BACKEND=hashing` (lighter, but retrieval is lexical instead of semantic).

## 2. Deploy the web UI on Vercel
1. Vercel dashboard → **Add New → Project** → import this repo.
2. **Root Directory: `frontend`** (Framework: Next.js is detected automatically).
3. **Environment Variables:** `NEXT_PUBLIC_API_URL` = your Render URL, e.g. `https://querymind-api.onrender.com` (no trailing slash). This value is baked in at build time, so changing it later needs a redeploy.
4. **Deploy.** Note the URL, e.g. `https://querymind.vercel.app`.

(CLI alternative: `cd frontend && npx vercel --prod`, after `npx vercel login`.)

## 3. Connect them (CORS)
In Render → Environment, set **`CORS_ORIGINS`** to your Vercel URL (`https://querymind.vercel.app`) and save (the service redeploys). To also allow Vercel preview deployments, set `CORS_ORIGIN_REGEX` to e.g. `https://querymind-[a-z0-9-]+\.vercel\.app`.

## 4. Check it
- Open the Vercel URL and ask a question; try "Delete all orders" (refused) and a revenue question.
- Open **Admin**: it asks for the admin token you copied from Render. It is kept only for the browser tab session; **Lock admin** forgets it.
- Visitors can use the Ask page but cannot reach any admin endpoint without the token.

## Configuration reference (Render environment)
| Variable | Purpose | Default in `render.yaml` |
|---|---|---|
| `ANTHROPIC_API_KEY` | Pays for the model calls | *(you set it)* |
| `ADMIN_TOKEN` | Locks `/admin/*` and the Admin UI | generated |
| `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` | Which web origins may call the API | *(you set it)* |
| `RATE_LIMIT_PER_HOUR` | Questions per visitor (by IP) per hour | 30 |
| `DAILY_QUERY_CAP` | Hard ceiling on questions per day, all visitors | 500 |
| `RATE_LIMIT_PROXY_HOPS` | Trusted proxies in front of the API | 1 |
| `ALLOW_TABLE_IMPORT` | Set `false` to disable CSV table import | true |
| `LLM_MODEL` | Model used for SQL | `claude-sonnet-4-20250514` |
| `SEMANTIC_CACHE` | Reuse answers to repeated questions (saves tokens) | true |

`DAILY_QUERY_CAP` is your safety net: at about 1.1 cents per fresh question, 500 a day caps spend at roughly $5.50/day worst case (less with the cache). Lower it if you want.

## Things to know
- **Data persistence:** logs, admin edits, imported tables and the vector index live on the Render disk and survive redeploys. The demo business database is created once on first boot (delete the disk or `business.db` to reset).
- **Rate limits are per server process** and reset on restart, which is fine for a single container. Do not scale to multiple instances without moving them to a shared store.
- **Cold starts:** Render keeps paid services running; the first question after a restart is slower while the model loads.
- **Single admin secret:** there are no per-user accounts. Rotate the token by changing `ADMIN_TOKEN` in Render. For multi-user admin, add a real login before sharing the token widely.
- **Imported CSV data** is visible to anyone who can ask a question about it, except columns you flagged sensitive. Do not import data you would not want users to query.
- **Costs:** see the estimate in the README conversation: roughly Render $25/mo + Anthropic usage (about 1.1 cents per fresh question on Sonnet) + Vercel $0 on Hobby (personal/non-commercial) or $20 on Pro.
