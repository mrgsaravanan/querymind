#!/bin/sh
# Container start: build the demo business database on first boot (if missing), then run the API.
set -e
BIZ="${BUSINESS_DB_PATH:-data/business.db}"
if [ ! -f "$BIZ" ]; then
  echo "First start: seeding demo database at $BIZ"
  mkdir -p "$(dirname "$BIZ")" "$(dirname "${ADMIN_DB_PATH:-data/admin.db}")"
  python data/seed_db.py --db "$BIZ"
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
