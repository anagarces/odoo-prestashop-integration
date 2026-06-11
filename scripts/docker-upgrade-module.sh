#!/usr/bin/env bash
# Actualiza o instala el módulo connector_prestashop en Odoo (Docker)
set -euo pipefail

MODULE="${1:-connector_prestashop}"
DATABASE="${2:-stylesync}"
MODE="${3:-upgrade}" # upgrade | install

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  DATABASE="${POSTGRES_DB:-$DATABASE}"
fi

cd "$PROJECT_ROOT"

echo ""
echo "[1/3] Deteniendo Odoo..."
docker compose stop odoo

if [[ "$MODE" == "install" ]]; then
  echo "[2/3] Instalando módulo $MODULE en base '$DATABASE'..."
  docker compose run --rm odoo odoo -i "$MODULE" -d "$DATABASE" --stop-after-init
else
  echo "[2/3] Actualizando módulo $MODULE en base '$DATABASE'..."
  docker compose run --rm odoo odoo -u "$MODULE" -d "$DATABASE" --stop-after-init
fi

echo "[3/3] Reiniciando Odoo..."
docker compose up -d odoo

echo ""
echo "Módulo $MODULE listo. Odoo: http://localhost:8069"
echo ""
