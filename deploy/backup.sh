#!/bin/sh
# Backs up everything that matters (admin.db, business.db, vector index) to ./backups/. Run from the project folder.
# The API is stopped for a few seconds so the SQLite files are copied in a consistent state.
set -e
mkdir -p backups
docker compose stop api
docker run --rm -v querymind_data:/data -v "$PWD/backups":/backup alpine \
  tar czf "/backup/querymind-$(date +%Y%m%d-%H%M).tar.gz" -C /data .
docker compose start api
ls -lh backups | tail -3
