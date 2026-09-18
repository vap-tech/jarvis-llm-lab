#!/usr/bin/env bash
set -euo pipefail

# Recreates the captured installation on Arch Linux. Run from this repository as root.
LLAMA_CPP_COMMIT="0fcb3760b2b9a3a496ef14621a7e4dad7a8df90f"
SERVICE_USER="${SERVICE_USER:-kot}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="/home/${SERVICE_USER}/llama.cpp"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (for example: sudo $0)" >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Missing service user: $SERVICE_USER" >&2
  exit 1
fi

pacman -S --needed --noconfirm \
  base-devel cmake git glslang nginx python python-pip shaderc \
  vulkan-headers vulkan-icd-loader vulkan-radeon vulkan-tools

if [[ ! -d "$LLAMA_DIR/.git" ]]; then
  sudo -u "$SERVICE_USER" git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
fi
sudo -u "$SERVICE_USER" git -C "$LLAMA_DIR" fetch origin "$LLAMA_CPP_COMMIT"
sudo -u "$SERVICE_USER" git -C "$LLAMA_DIR" checkout --detach "$LLAMA_CPP_COMMIT"
sudo -u "$SERVICE_USER" cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_VULKAN=ON
sudo -u "$SERVICE_USER" cmake --build "$LLAMA_DIR/build" --config Release -j"$(nproc)"

install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" /opt/archsrv-rag/app
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" /srv/rag /srv/projects
install -d -m 0755 /etc/archsrv-rag /etc/llama-server /var/www/archsrv

cp -a "$REPO_ROOT/rag-api/." /opt/archsrv-rag/app/
chown -R "$SERVICE_USER:$SERVICE_GROUP" /opt/archsrv-rag/app
python -m venv /opt/archsrv-rag/.venv
/opt/archsrv-rag/.venv/bin/pip install --upgrade pip
/opt/archsrv-rag/.venv/bin/pip install -r /opt/archsrv-rag/app/requirements.txt
chown -R "$SERVICE_USER:$SERVICE_GROUP" /opt/archsrv-rag/.venv

cp -a "$REPO_ROOT/web-ui/." /var/www/archsrv/
cp -a "$REPO_ROOT/system/etc/llama-server/." /etc/llama-server/
cp "$REPO_ROOT/deploy/projects.empty.json" /etc/archsrv-rag/projects.json
cp "$REPO_ROOT/system/etc/nginx/nginx.conf" /etc/nginx/nginx.conf
install -m 0755 "$REPO_ROOT/system/usr-local-bin/llama-server-launch" /usr/local/bin/llama-server-launch
install -m 0755 "$REPO_ROOT/system/usr-local-bin/llama-model-select" /usr/local/bin/llama-model-select
install -m 0755 "$REPO_ROOT/system/usr-local-bin/llama-manager.py" /usr/local/bin/llama-manager.py
cp "$REPO_ROOT/system/systemd/"*.service /etc/systemd/system/

# The captured files use /home/kot and User=kot. Adapt them when SERVICE_USER differs.
if [[ "$SERVICE_USER" != "kot" ]]; then
  sed -i "s|/home/kot|/home/$SERVICE_USER|g; s|User=kot|User=$SERVICE_USER|g; s|Group=kot|Group=$SERVICE_GROUP|g" \
    /usr/local/bin/llama-server-launch \
    /usr/local/bin/llama-manager.py \
    /etc/systemd/system/llama-server.service \
    /etc/systemd/system/archsrv-rag.service
fi

chown "$SERVICE_USER:$SERVICE_GROUP" /etc/archsrv-rag/projects.json
systemctl daemon-reload
systemctl enable --now llama-server.service llama-manager.service archsrv-rag.service nginx.service

echo "Installation complete. The selected model will be downloaded on first start."
echo "UI: http://SERVER_IP/"

