# Hosting QueryMind on a Hetzner server (everything on one machine)

One small Hetzner Cloud server runs three containers: the **web UI**, the **API** and **Caddy** (automatic free HTTPS). You pay Hetzner for the server and Anthropic for model usage; nothing else.

```
Browser ──HTTPS──▶ Caddy ──/api/*──▶ API (FastAPI + SQLite + ChromaDB, data on a Docker volume)
                     └──everything else──▶ Web UI (Next.js)                    │
                                                                               └──▶ Anthropic API
```

> The compose file, Dockerfiles and Caddy config were checked for syntax and the web build was verified, but they could not be test-run on the machine they were written on (no Docker there). Watch the first `docker compose up` output; fixes are usually small.

## Part 1: Subscribe to Hetzner (you do this; about 10 minutes)

I can't create accounts or enter payment details for you.

1. Go to **console.hetzner.cloud** and register (email + password, then confirm the email). Hetzner may ask for a payment method (card or PayPal) and sometimes an identity check for new accounts.
2. Create a **Project** (any name, e.g. `querymind`).
3. On your own computer, make an SSH key if you don't have one, and copy the public part:
   ```bash
   ssh-keygen -t ed25519 -C "querymind"
   cat ~/.ssh/id_ed25519.pub
   ```
4. In the project: **Add Server**
   - **Location:** the closest to your users (Germany/Finland are the cheapest; US locations cost about 20% more).
   - **Image:** Ubuntu 24.04.
   - **Type:** a **shared vCPU plan with 4 GB RAM** (currently called CX23, about €6 a month; names and prices change, so read the screen). Do not go below 2 GB, because the app needs about 1 GB just for itself.
   - **Networking:** keep **IPv4** enabled (about €0.50 a month extra).
   - **SSH key:** paste the public key from step 3.
   - **Firewall:** create one that allows inbound **22** (SSH), **80** and **443** (web) only.
   - **Backups (optional):** about 20% extra. Fine if you want Hetzner-side snapshots, though the included `backup.sh` also works.
5. Click **Create & Buy now**. Note the server's **IPv4 address**.

Billing is hourly and capped at the monthly price, so you can delete the server any time and stop paying.

## Part 2: Point a name at the server
HTTPS needs a name, not a bare IP address. Pick one:
- **A domain you own** (about $10 a year): add an **A record** `app.yourdomain.com → <server IPv4>`.
- **Free, no domain:** use `<ip-with-dashes>.sslip.io`, for example the IP `203.0.113.10` becomes `203-0-113-10.sslip.io`. It resolves to your IP automatically. (It's a shared free service, so certificate limits can occasionally bite. A real domain is more reliable.)

## Part 3: Set up the server
```bash
ssh root@<server-ip>

# a little safety margin for memory spikes
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Docker
curl -fsSL https://get.docker.com | sh

# the code
git clone https://github.com/mrgsaravanan/querymind.git
cd querymind

# configuration
cp deploy/env.example .env
nano .env        # set DOMAIN, ANTHROPIC_API_KEY, ADMIN_TOKEN (generate with: openssl rand -hex 24)

# build and start (first build takes several minutes)
docker compose up -d --build
docker compose logs -f api     # wait for "Uvicorn running" (first start also seeds the demo data); Ctrl+C to leave
```
If the repository is private, clone with a GitHub access token or deploy key instead.

## Part 4: Check it
- Open `https://<your DOMAIN>`: the Ask page loads over HTTPS.
- `https://<your DOMAIN>/api/health` shows `"status":"ok"`.
- Ask a question; try "Delete all orders" (politely refused).
- Open **Tables** or any admin page: it asks for your `ADMIN_TOKEN`.
- If HTTPS fails: `docker compose logs caddy` (usually the DNS name doesn't point at the server yet, or ports 80/443 are blocked by the firewall).

## Day-to-day
| Task | Command (in the `querymind` folder) |
|---|---|
| Update to the latest code | `git pull && docker compose up -d --build` |
| See logs | `docker compose logs -f api` (or `web`, `caddy`) |
| Restart | `docker compose restart` |
| Back up data | `./deploy/backup.sh` (brief API pause, writes `backups/*.tar.gz`; copy it off the server) |
| Restore a backup | `docker compose down && docker run --rm -v querymind_data:/data -v "$PWD/backups":/b alpine sh -c "rm -rf /data/* && tar xzf /b/<file>.tar.gz -C /data" && docker compose up -d` |
| Change the admin token or limits | edit `.env`, then `docker compose up -d` |
| Check memory | `free -h` and `docker stats --no-stream` |

Logs, edits, imported tables and the vector index live on the `querymind_data` volume and survive updates and reboots.

## Security checklist
- **Keep `.env` private** (it holds your API key and admin token). It is in `.gitignore`.
- Set a **monthly spend limit** in the Anthropic console. `DAILY_QUERY_CAP` is a second safety net.
- Use **SSH keys only**: after your key works, disable password login (`PasswordAuthentication no` in `/etc/ssh/sshd_config`, then `systemctl restart ssh`).
- Turn on automatic security updates: `apt install unattended-upgrades`.
- The admin area has **one shared token**, not per-user accounts. Share it carefully, and rotate it by editing `.env`.
- Visitors can ask questions without logging in (rate-limited per IP). If this should be private, put it behind a VPN or add login first.

## Costs (monthly, approximate)
Server about €6 to €6.50 + IPv4 €0.50 (check Hetzner's current price) · domain about $1 (optional) · Anthropic usage about 1.1 cents per fresh question on Sonnet (about $78 for 10,000 questions if 30% repeat and are served from the cache). No hosting fee for the UI, since it runs on the same server.

## Troubleshooting
- **Build killed or out of memory:** confirm the server has 4 GB and the swap file is active (`free -h`); retry `docker compose up -d --build`.
- **"Cannot reach the API" in the browser:** `NEXT_PUBLIC_API_URL` is baked in at build time. After changing `DOMAIN`, rebuild: `docker compose up -d --build web`.
- **429 "Too many questions":** the per-visitor or daily limit was reached; adjust `RATE_LIMIT_PER_HOUR` / `DAILY_QUERY_CAP` in `.env`.
- **Admin pages say the token is wrong:** use the `ADMIN_TOKEN` value from `.env`; after editing it, run `docker compose up -d`.
- The API's built-in docs page is not usable under the `/api` path; use the app itself.
