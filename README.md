# QueryMind AI

A domain-agnostic **Text-to-SQL platform**: a business user types a question in plain English and gets a result table plus a short written summary, with no SQL required. Data engineers manage the schema notes, few-shot examples, guardrails, model settings and query logs from an Admin UI.

- **Backend:** FastAPI · Pydantic v2 · SQLAlchemy · `sqlglot` · ChromaDB · Python 3.11+
- **Frontend:** Next.js 14 (App Router) · TypeScript · Tailwind · TanStack Table · Recharts
- **LLM:** behind a provider interface: **your Claude subscription via the `claude` CLI (no API key)**, Anthropic API, OpenAI or Ollama

```
NL question
   │
   ▼
┌────────────┐  UNSUPPORTED (UPDATE/DELETE/DDL)   ┌──────────────────────────┐
│ Classifier │ ──────────────────────────────────▶│ friendly refusal, logged │  (never reaches the generator)
│ keywords + │                                    └──────────────────────────┘
│ LLM (JSON) │
└─────┬──────┘
      ▼
┌─────────────┐   ┌───────────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌───────────────┐
│Schema Linker│──▶│ Examples Retriever│──▶│ SQL Generator│──▶│ SQL Validator │──▶│ SQL Executor │──▶│Result Formatter│
│ synonyms,   │   │ ChromaDB top-k    │   │ LLM, SELECT- │   │ sqlglot AST   │   │ read-only DB │   │ table + summary│
│ ambiguities │   │ few-shot pairs    │   │ only prompt  │   │ + 1 retry     │   │ + timeout    │   └───────────────┘
└─────────────┘   └───────────────────┘   └──────────────┘   └───────┬───────┘   └──────┬───────┘
                                                  ▲                  │ invalid          │ DB error
                                                  └──── 1 retry ─────┘                  ▼
                                                  ▲                        self-healing: 1 retry with the error
                                                  └────────────────────────────────────┘
```

Every stage has typed Pydantic input/output models (`backend/app/schemas/`), takes its dependencies by injection, and can be called and unit-tested alone. The orchestrator wires them, records per-stage timings and writes a log row for every outcome.

**Full design write-up with diagrams: [ARCHITECTURE.md](ARCHITECTURE.md).**

## Domain, dialect and key decisions

| Decision | Choice | Why |
|---|---|---|
| Domain | **E-commerce orders** | Familiar to everyone, and it naturally provides joins, aggregates, date arithmetic and a real "revenue" ambiguity. |
| Dialect | **SQLite**, behind a one-file dialect abstraction ([`dialects.py`](backend/app/db/dialects.py)) | Zero setup; PostgreSQL/MySQL entries exist for prompting and transpiling, but only SQLite is exercised end-to-end. |
| LLM | `claude_cli` (Claude subscription), Anthropic API, OpenAI, Ollama | Provider, model and temperature come from the Model Config panel, never from stage logic. |
| Vector store | ChromaDB (persistent), Chroma's bundled MiniLM embeddings | An offline `hashing` embedding backend exists for tests (`EMBEDDING_BACKEND=hashing`). |
| Python | **3.12** (3.11+ works) | Some pinned wheels (e.g. `pydantic-core`) have no 3.14 build; `make install` creates a 3.12 venv with `uv`. |
| "Today" | Fixed to **2025-12-31** (`REFERENCE_DATE`) | The synthetic data ends there, so "last quarter" has a stable, testable meaning. |

### Database (7 tables, seeded, deterministic)

`customers` · `categories` · `products` · `orders` · `order_items` (junction: orders ↔ products) · `payments` · `reviews` — 1,200 customers, 1,000 products, 5,000 orders, 10,313 order lines. Seeding uses a fixed RNG seed and is idempotent. Full column-by-column documentation: **[data dictionary](backend/data/data_dictionary.md)**.

**Documented ambiguity — "revenue":** it can mean `orders.total_amount` (order grand total, including shipping, net of discounts) or `order_items.line_total` (merchandise only). The two differ by about 5% overall. The convention (product/category revenue → `line_total`; everything else → `total_amount`; exclude cancelled orders) is stated in [`domain_notes.md`](backend/data/domain_notes.md) and shown to the model. The Schema Linker flags the ambiguity, and the chat UI offers "Did you mean…" buttons that resubmit with the user's choice.

## Quickstart

Prerequisites: Python 3.11 or 3.12 (or [`uv`](https://docs.astral.sh/uv/)), Node 18+, and one LLM option: a **Claude subscription** with the [Claude Code CLI](https://claude.com/claude-code) logged in (`claude login`), or an Anthropic/OpenAI API key, or a local Ollama.

```bash
make install            # venv + backend deps + frontend deps
cp .env.example backend/.env && $EDITOR backend/.env     # set LLM_PROVIDER=claude_cli + LLM_MODEL=sonnet (subscription), or add an API key
make seed               # build the demo business database
make index-examples     # seed the 41 few-shot examples and index them in ChromaDB (downloads an ~80 MB embedding model once)
make backend            # API on http://localhost:8000   (terminal 1)
make frontend           # UI  on http://localhost:3000   (terminal 2)
```

The frontend reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). The backend creates `data/admin.db` and seeds the examples on first start, so `make index-examples` is only needed to (re)build the index explicitly. Without an API key everything except LLM-backed answering works: the admin panels, and destructive requests are still refused by the keyword pre-check.

Other targets: `make test` (offline), `make eval`, `make eval-selftest`.

### Using your Claude subscription (no API key)

Set `LLM_PROVIDER=claude_cli` and `LLM_MODEL=sonnet` in `backend/.env` (or pick *Claude subscription* in the Model panel). The provider ([`claude_cli_provider.py`](backend/app/llm/claude_cli_provider.py)) calls the official `claude` CLI in headless mode, which uses your logged-in claude.ai account; the subscription's login token is never used directly with the API.

- **Locked down:** tools are disabled, MCP servers/hooks/memory/`CLAUDE.md` are not loaded, it runs in an empty temp directory, and the user's text goes via stdin, so a prompt injection cannot read files or run commands.
- **Never bills the API:** `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` are stripped from the child process environment.
- **Trade-offs:** the CLI has no temperature or token-limit flag (those settings are ignored), outputs are therefore not guaranteed deterministic (the eval cache pins them for reruns), and each call adds a few seconds of start-up (about 15 s per question end to end: classify, generate, summarize). Use model aliases such as `sonnet`; dated IDs like `claude-sonnet-4-20250514` are not served on the subscription. Usage counts against your subscription limits.
- **Verified:** real questions were run through the full pipeline on this provider (e.g. revenue by category, and "orders last quarter" returning 882, matching the ground truth).

## Sample queries

> The following outputs were captured from the real code and database. Answers in your install will carry an LLM-written summary line; SQL for the first two comes from the example library and was run through the real validator and read-only executor.

**1. "What is the total revenue by product category?"** (aggregate, uses `line_total` per the convention)
```sql
SELECT c.name AS category, ROUND(SUM(oi.line_total), 2) AS revenue
FROM order_items oi JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id
WHERE o.status != 'cancelled' GROUP BY c.name ORDER BY revenue DESC
```
| category | revenue |
|---|---:|
| Electronics | 548,966.56 |
| Automotive | 108,307.10 |
| Home & Kitchen | 101,710.83 |
| Sports | 101,235.48 |
| Office | 99,280.13 |
| … 7 more rows | |

**2. "Who are the top 10 customers by total spend?"** (join + aggregate, revenue at *order* level → `total_amount`)

| name | total_spend |
|---|---:|
| Aisha Chen | 60,423.80 |
| Ethan Dubois | 37,613.60 |
| Aisha Okafor | 28,487.32 |
| Raj Martin | 23,453.07 |
| Emma Moreau | 15,963.50 |
| … 5 more rows | |

**3. A blocked request** — "Delete all orders from 2024" → status `unsupported`, no SQL generated:
> I can only answer read-only questions about your data (looking things up, counting, summing, comparing over time). I can't modify, delete or restructure data. Try rephrasing as a question, e.g. "How many orders were cancelled last month?"

**4. Sensitive data is invisible.** `SELECT * FROM customers` is rewritten by the validator to list only non-sensitive columns:
```sql
SELECT customers.id AS id, customers.name AS name, customers.country AS country,
       customers.signup_date AS signup_date FROM customers AS customers LIMIT 100
```
and `SELECT email FROM customers` is rejected: *"Column 'customers.email' is sensitive and cannot be queried."*

## Deploying to the cloud (Vercel + Render)

The web UI deploys to **Vercel**; the API runs as a container on **Render** (it needs a persistent disk, which Vercel does not offer). The repo includes a [`Dockerfile`](backend/Dockerfile), a [`render.yaml`](render.yaml) blueprint and step-by-step instructions in **[DEPLOY.md](DEPLOY.md)**. For a single cheap server instead, **[HETZNER.md](HETZNER.md)** runs the whole stack (UI, API, automatic HTTPS) with `docker compose` on one Hetzner VM. Public deployments need an Anthropic API key (the subscription CLI login is personal) and add three protections, all off by default for local use: an **admin token** (`ADMIN_TOKEN`) that locks the Admin UI and `/admin/*`, a **per-visitor rate limit** and a **daily question cap** (`RATE_LIMIT_PER_HOUR`, `DAILY_QUERY_CAP`) to protect API spend, and configurable **CORS**.

## Admin UI walkthrough

| Panel | What it does |
|---|---|
| **Schema** (`/admin/schema`) | Browse tables and columns; edit descriptions inline (use `(also: synonym, …)` to teach the linker aliases); toggle **sensitive** per column. Sensitive columns are removed from every LLM prompt, the linker output, validation and results. |
| **Tables** (`/admin/tables`) | **Add your own data:** upload a CSV, review detected column types, safe names and suggested descriptions, tick sensitive columns (emails, phones and similar are pre-ticked), then import. The table is queryable immediately. Replace or delete tables you imported; original tables are protected. |
| **Examples** (`/admin/examples`) | Add / edit / delete few-shot pairs, label them by query type, and run a **semantic search**. Every write re-embeds or removes the vector, and SQL is validated before it is saved. |
| **Logs** (`/admin/logs`) | Every question with its SQL, status, latency and row count; filter by status, text and date; expand a row for the error and per-stage timings; **export CSV**. |
| **Guardrails** (`/admin/guardrails`) | Toggle each SQL operation, set the max row limit (1–100,000), restrict allowed table prefixes and schemas. |
| **Model** (`/admin/model`) | Provider (Anthropic / OpenAI / Ollama), model name, temperature, dialect, max token budget. |

All admin changes persist to `admin.db` and apply to the **next request without a restart** (each request takes a fresh snapshot of schema, guardrails and model config).

### Adding your own tables (CSV import)

Open **Tables** in the Admin UI, choose a CSV (comma, semicolon, tab or pipe separated, header row, up to 10 MB / 100,000 rows) and review the preview:

- **Types** are detected from all rows: `INTEGER`, `REAL`, `DATE` (`YYYY-MM-DD`), `DATETIME`, else `TEXT`. Zip codes and padded ids (`0123`) and very long digit strings stay `TEXT` so nothing is silently altered. Dates in other formats (`31/01/2024`) trigger a warning, because date questions only work with ISO dates.
- **Names** are rewritten into safe SQL identifiers (`Order Date` becomes `order_date`; words SQLite or `sqlglot` cannot use unquoted, such as `order`, become `order_col`). You can edit them.
- **Sensitive columns** are suggested from the column name and the values (emails, phone numbers, national IDs) and are pre-ticked. You decide; ticked columns are hidden from every AI prompt, validation and result, exactly like the built-in ones.
- After importing, add a few example questions for the new subject area and adjust `backend/data/domain_notes.md` (its rules are e-commerce specific).

How it stays safe: parsing is stateless and in memory; every identifier is validated and every value is inserted as a bound parameter, so hostile cell contents are stored as plain text; the import runs in one transaction (all or nothing); only this admin action uses a read-write connection, while the query path stays `mode=ro`; only tables created by the importer can be replaced or deleted. Set `ALLOW_TABLE_IMPORT=false` to disable the feature (for example on a shared deployment). There is no login on the Admin UI, so do not expose this feature to untrusted users.

## Safety design

Defence in depth, so no single layer is the only thing standing between a prompt and the data:

1. **Classifier pre-check:** deterministic keyword/regex check for destructive intent runs *before* any LLM call, so these requests are refused even with no API key. `UNSUPPORTED` never reaches the generator.
2. **Prompting:** the generator is told SELECT-only and to treat the question as untrusted data.
3. **AST validator** ([`sql_validator.py`](backend/app/pipeline/sql_validator.py)): decisions are made on the `sqlglot` AST, not substrings, so a `DELETE` hidden in a CTE or comment is caught and a column named `updated_at` is not a false positive. It rejects DROP/DELETE/UPDATE/INSERT/TRUNCATE/ALTER/CREATE (unless the admin toggles them), plus `PRAGMA`, `ATTACH`, `REPLACE`, transactions and `load_extension()`; rejects stacked queries; verifies every table and column exists; enforces table-prefix/schema scope; and appends or clamps `LIMIT`. **The SQL that runs is re-rendered from the validated AST**, so comments and parser quirks cannot smuggle anything through.
4. **Read-only connection:** SQLite is opened with `mode=ro`. A write fails at the database layer even if validation is bypassed (tested directly).
5. **Sensitive-column exclusion:** flagged columns never appear in the schema shown to any LLM, the linker, validation (including through CTEs/subqueries/`SELECT *`), or the result table. A test captures every prompt sent to the LLM and asserts no sensitive column name appears.
6. **Execution limits:** query timeout, hard row cap, and safe error messages: raw database errors are logged internally and never returned to the client.

## Evaluation

```bash
make eval            # full run: 25-question accuracy suite + guardrail attack suite (needs an LLM key)
make eval-selftest   # harness plumbing check with an oracle "LLM" - NOT model results
python backend/eval/run_eval.py --no-cache --limit 5     # options: --no-cache, --limit N, --threshold, --skip-accuracy, --skip-guardrails
```

Outputs `reports/eval_report_<timestamp>.md` and `.json`; exit code 0 = pass, 1 = fail (Execution Accuracy < 50%, any missed attack, or any change to the database), 2 = accuracy could not be evaluated.

**How the metrics are computed**

- **Execution Accuracy:** the pipeline's final SQL and the ground-truth SQL are both run on the seeded database and compared row for row (numbers rounded to 2 dp, int = float, strings trimmed, column aliases ignored, row order significant only for top-N questions).
- **Exact Match / Semantic Match:** both queries are parsed and re-rendered canonically with `sqlglot` (the auto-appended `LIMIT` is ignored); equal text is an exact match, and ASTs with no `sqlglot.diff` edits count as a semantic match.
- **Guardrails Compliance:** 28 attacks (direct DDL/DML, stacked queries, case and comment obfuscation, CTE-wrapped writes, `PRAGMA`/`ATTACH`/`load_extension`, PII reads, natural-language requests and prompt injections). An attack is *blocked* if no destructive SQL ran and no sensitive column was returned; the database is fingerprinted before and after.
- **Determinism:** temperature 0, fixed-seed data and anchor date, on-disk cache of LLM replies, semantic cache disabled during evaluation. The 25 test questions are disjoint from the example library (a test enforces this).

**Latest results** (`claude_cli` / `sonnet`, 25 questions + 28 attacks; full report: [`reports/sample_report.md`](reports/sample_report.md); first-run baseline: [`reports/baseline_run1_report.md`](reports/baseline_run1_report.md))

| Metric | Run 1 (baseline) | Run 2 (after tightening the cancelled-orders note) |
|---|---:|---:|
| **Execution Accuracy** | 72% (18/25) | **80% (20/25)** |
| Exact Match / Semantic Match | 12% / 12% | 12% / 12% |
| **Guardrails Compliance** | 100% (28/28) | **100% (28/28)**, database unchanged |

| Query type | Run 1 | Run 2 |
|---|---:|---:|
| SELECT_SIMPLE | 80% (4/5) | 100% (5/5) |
| SELECT_AGGREGATE | 71% (5/7) | 71% (5/7) |
| SELECT_JOIN | 67% (4/6) | 83% (5/6) |
| SELECT_TEMPORAL | 71% (5/7) | 71% (5/7) |

Classifier agreement with the labelled type: 96%. Latency per question (classify + generate + execute, no summary) is about 9.4 s on a cold run; run 2's lower figure (5.0 s) is not comparable because its classifier calls were served from the eval cache.

**What changed between runs:** only `domain_notes.md`. The note about cancelled orders was split so it applies to money totals and units sold, while plain listing and counting of orders includes every status. This fixed q03 and q18 outright and removed the cancelled-orders error from q14. The ground truth and test questions were not edited, and the new note uses generic examples (not test wording).

**The 5 remaining failures** (generated vs expected SQL are in the report) are all strictness or format issues, not wrong logic:
- *Extra column (q10, q12, q14, q24):* the right answer plus a helpful extra column (the count, the revenue, the order total, the date); Execution Accuracy requires the exact column count.
- *Label format (q23):* quarters returned as "Q1…Q3" instead of 1…3.

Exact/Semantic Match are low by design: the model's SQL is correct but written differently (aliases, `<>` vs `!=`, explicit `AS`, added `ORDER BY`/columns), and `sqlglot.diff` is strict. Treat Execution Accuracy as the primary measure.

**Caveats:** one 25-question suite (each question is 4 points); the suite was run twice, so run 2 is a tuned result on a test set that is no longer a clean holdout; the `claude_cli` provider cannot set temperature, so reruns can differ (the eval cache pins them once recorded). The tuning was limited to the one note; no other prompt or example changes were made.

## Bonus features implemented

| Bonus | Where |
|---|---|
| Self-healing SQL | On an execution error the orchestrator retries once with the DB error in the prompt; the fix is used only if it validates and runs. |
| Ambiguity resolution | Linker flags ambiguities; the chat UI shows "Did you mean…" buttons that resubmit with a `clarification`. |
| Query explanation mode | "Explain mode" toggle shows the model's plain-English explanation prominently (the SQL panel always has it). |
| Chart auto-generation | Two-column results with one numeric column render a bar chart, or a line chart for time-like labels. |
| Multi-dialect | "Also show SQL as…" rewrites the SQL with `sqlglot.transpile()` (best effort, display only; execution uses the configured dialect). |
| Semantic caching | Near-identical repeated questions reuse the cached SQL and summary with zero LLM calls. The SQL is still re-validated and re-executed on every hit, and entries are invalidated when model config, guardrails, schema or sensitive flags change. Toggle with `SEMANTIC_CACHE`. |
| Voice input | Microphone button using the Web Speech API (shown only in browsers that support it, e.g. Chrome). |

## Project layout

See [ARCHITECTURE.md](ARCHITECTURE.md) for how the parts fit together. Folder map:

```
backend/app/{schemas,pipeline,llm,services,api,db}   typed stages, providers, admin services, routers
backend/data/                                          schema.sql, seed_db.py, data_dictionary.md, examples_seed.json, domain_notes.md
backend/eval/                                          test_set.json, guardrail_attacks.json, run_eval.py, metrics.py, report template
backend/tests/                                         offline pytest suite (220 tests)
frontend/src/app/                                      chat page + admin/{schema,examples,logs,guardrails,model}
reports/                                               generated evaluation reports
```

`make test` runs the suite fully offline (mock LLM, offline embeddings, temp databases): classifier routing, linker with sensitive columns, retriever sync on CRUD, validator (AST blocking, stacked queries, schema check, limit injection), executor read-only enforcement, formatter empty results, orchestrator with a fake LLM, every admin API path including persistence across app restarts, the evaluation harness, and the bonus features.

## Known limitations and future work

- **Accuracy is measured on one 25-question suite (72% before, 80% after one domain-note fix);** the second figure is tuned on that suite, so treat it as optimistic. The model often adds an extra helpful column, which strict Execution Accuracy counts as a miss (see Evaluation).
- **Only SQLite is exercised end-to-end.** PostgreSQL/MySQL have dialect entries and transpilation, but the read-only role setup, timeouts and a live connection path are not implemented or tested. No `docker-compose` is included.
- **Linker is lexical:** it matches names and `(also: …)` synonyms; it does not use embeddings, so paraphrases outside the synonym lists are left to the generator and retrieved examples.
- **Sensitive-column detection is by flag, not by content:** a sensitive value reachable through a differently named column would not be caught.
- **Date handling relies on the fixed reference date** passed in the prompt; relative phrases beyond "this/last month, quarter, year" and "last N days" are interpreted by the model.
- **Explain mode** shows the one-to-two sentence explanation the generator already returns, not a separate step-by-step breakdown.
- **Authentication is a single shared admin token** (no per-user accounts), and the public Ask endpoint has only IP-based rate limiting. Without `ADMIN_TOKEN` the API and Admin UI are open, and the CSV importer can create and delete the tables it imported. For any public deployment set `ADMIN_TOKEN` (and consider `ALLOW_TABLE_IMPORT=false`); see DEPLOY.md.
- **CSV import is SQLite-only and basic:** one table per file, no primary/foreign keys or indexes, no automatic date-format conversion, no append-to-existing mode.
- **Query timeouts** are implemented for SQLite only.
- **Future work:** an LLM-assisted linker, per-user permissions and row-level security, answer feedback ("was this right?") feeding the examples library, streaming responses, PostgreSQL/MySQL read-only roles.
