#!/usr/bin/env bash
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=inv_password="$INVENTORY_DB_PASSWORD" --set=work_password="$WORKSHOP_DB_PASSWORD" --set=vision_password="$VISION_DB_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE inventory LOGIN PASSWORD :'inv_password';
CREATE ROLE workshop LOGIN PASSWORD :'work_password';
CREATE ROLE vision LOGIN PASSWORD :'vision_password';
CREATE SCHEMA inventory AUTHORIZATION inventory;
CREATE SCHEMA workshop AUTHORIZATION workshop;
CREATE SCHEMA vision AUTHORIZATION vision;
ALTER ROLE inventory IN DATABASE stocklane SET search_path TO inventory,public;
ALTER ROLE workshop IN DATABASE stocklane SET search_path TO workshop,public;
ALTER ROLE vision IN DATABASE stocklane SET search_path TO vision,public;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
