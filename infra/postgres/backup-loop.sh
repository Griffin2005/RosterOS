#!/bin/bash
# Local backups: the primary continuously archives WAL into /backups/wal
# (archive_command); this loop adds a compressed logical dump every 15 minutes
# and keeps the last 96 (24 hours). Restore: pg_restore -d rosteros <file>.
set -e
mkdir -p /backups/dumps
until pg_isready -h db -U "$POSTGRES_USER"; do sleep 2; done
# wait for the API to create the schema, so the first dump isn't empty
until PGPASSWORD="$POSTGRES_PASSWORD" psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
      "select to_regclass('public.roster')" | grep -q roster; do sleep 5; done
while true; do
  f="/backups/dumps/rosteros-$(date -u +%Y%m%dT%H%M%SZ).dump"
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$f" \
    && echo "backup ok: $f"
  ls -1t /backups/dumps/*.dump 2>/dev/null | tail -n +97 | xargs -r rm -f
  sleep 900
done
