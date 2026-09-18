#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-192.168.0.64}"
REMOTE_USER="${REMOTE_USER:-kot}"
REMOTE_PASSWORD="${REMOTE_PASSWORD:?Set REMOTE_PASSWORD in the environment}"
REMOTE_TMP_DIR="${REMOTE_TMP_DIR:-/tmp/archsrv-dist}"
REMOTE_WEB_ROOT="${REMOTE_WEB_ROOT:-/var/www/archsrv}"
REMOTE_NGINX_CONF="${REMOTE_NGINX_CONF:-/etc/nginx/nginx.conf}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
DIST_DIR="$FRONTEND_DIR/dist"
NGINX_CONF="$ROOT_DIR/backend/nginx.conf"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass is required for deployment" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required for deployment" >&2
  exit 1
fi

cd "$FRONTEND_DIR"
npm run build

sshpass -p "$REMOTE_PASSWORD" ssh -o StrictHostKeyChecking=no \
  "$REMOTE_USER@$REMOTE_HOST" "rm -rf '$REMOTE_TMP_DIR' && mkdir -p '$REMOTE_TMP_DIR'"

sshpass -p "$REMOTE_PASSWORD" scp -r "$DIST_DIR" "$NGINX_CONF" \
  "$REMOTE_USER@$REMOTE_HOST:$REMOTE_TMP_DIR/"

sshpass -p "$REMOTE_PASSWORD" ssh -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" "
set -e
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S mkdir -p '$REMOTE_WEB_ROOT'
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S find '$REMOTE_WEB_ROOT' -mindepth 1 -maxdepth 1 -exec rm -rf {} +
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S cp -a '$REMOTE_TMP_DIR/dist/.' '$REMOTE_WEB_ROOT/'
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S install -m 644 '$REMOTE_TMP_DIR/nginx.conf' '$REMOTE_NGINX_CONF'
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S nginx -t
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S systemctl enable --now nginx
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S systemctl reload nginx
"

echo "Frontend deployed to http://$REMOTE_HOST/"
