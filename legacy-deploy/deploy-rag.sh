#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-192.168.0.64}"
REMOTE_USER="${REMOTE_USER:-kot}"
REMOTE_PASSWORD="${REMOTE_PASSWORD:?Set REMOTE_PASSWORD in the environment}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAG_DIR="$ROOT_DIR/rag"
SERVER_DIR="$ROOT_DIR/server"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass is required for deployment" >&2
  exit 1
fi

sshpass -p "$REMOTE_PASSWORD" ssh -o StrictHostKeyChecking=no \
  "$REMOTE_USER@$REMOTE_HOST" "mkdir -p /tmp/archsrv-rag-deploy"

sshpass -p "$REMOTE_PASSWORD" scp -r "$RAG_DIR" "$SERVER_DIR/packages-arch.txt" \
  "$REMOTE_USER@$REMOTE_HOST:/tmp/archsrv-rag-deploy"

sshpass -p "$REMOTE_PASSWORD" ssh -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" "
set -e
mkdir -p /tmp/archsrv-rag-deploy
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S pacman -Sy --noconfirm --needed \$(grep -v '^#' /tmp/archsrv-rag-deploy/packages-arch.txt | tr '\n' ' ')
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S mkdir -p /opt/archsrv-rag /etc/archsrv-rag /srv/rag
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S chown -R kot:kot /srv/rag
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S rm -rf /opt/archsrv-rag/app
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S cp -a /tmp/archsrv-rag-deploy/rag /opt/archsrv-rag/app
if [ ! -f /etc/archsrv-rag/projects.json ]; then
  printf '%s\n' '$REMOTE_PASSWORD' | sudo -S install -m 644 /opt/archsrv-rag/app/projects.sample.json /etc/archsrv-rag/projects.json
fi
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S chown -R kot:kot /etc/archsrv-rag
if [ ! -d /opt/archsrv-rag/.venv ]; then
  printf '%s\n' '$REMOTE_PASSWORD' | sudo -S python -m venv /opt/archsrv-rag/.venv
fi
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S /opt/archsrv-rag/.venv/bin/pip install --upgrade pip
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S /opt/archsrv-rag/.venv/bin/pip install -r /opt/archsrv-rag/app/requirements.txt
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S install -m 644 /opt/archsrv-rag/app/archsrv-rag.service /etc/systemd/system/archsrv-rag.service
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S systemctl daemon-reload
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S systemctl enable --now archsrv-rag.service
printf '%s\n' '$REMOTE_PASSWORD' | sudo -S systemctl restart archsrv-rag.service
"

echo "RAG service deployed to $REMOTE_HOST"
