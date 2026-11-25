#!/bin/bash
# Streaming read replica: clone the primary once, then follow its WAL.
set -e
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "Cloning primary into $PGDATA ..."
  until pg_isready -h db -U "$POSTGRES_USER"; do sleep 2; done
  export PGPASSWORD="$REPLICATION_PASSWORD"
  pg_basebackup -h db -U replicator -D "$PGDATA" -R -X stream -P
  chmod 700 "$PGDATA"
fi
exec docker-entrypoint.sh postgres -c hot_standby=on
