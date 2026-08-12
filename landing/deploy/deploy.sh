#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${UHBSE_HOST:-root@89.108.70.42}"
REMOTE_DIR="/var/www/uhbse.tech"

cd "$ROOT"
npm run build
rsync -avz --delete dist/ "${HOST}:${REMOTE_DIR}/"
ssh "$HOST" 'nginx -t && systemctl reload nginx'
bash "$ROOT/deploy/indexnow.sh"
echo "Deployed to ${HOST}:${REMOTE_DIR}"
