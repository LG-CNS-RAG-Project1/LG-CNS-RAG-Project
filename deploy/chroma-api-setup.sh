#!/bin/bash
# Debian 서버의 Chroma 앞에 HTTPS와 개인별 키 인증을 설치한다.
set -euo pipefail
: "${CHROMA_PUBLIC_HOST:?HTTPS hostname is required}"
: "${CHROMA_AUTH_KEY_FILE:?SHA-256 key hash JSON path is required}"
if [[ ! "$CHROMA_PUBLIC_HOST" =~ ^[a-z0-9][a-z0-9.-]+[a-z0-9]$ ]]; then
    echo "Use a DNS hostname without a scheme, path, or port"
    exit 1
fi
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y caddy python3
systemctl stop caddy
if ! getent passwd idealens-auth >/dev/null; then
    useradd --system --user-group --no-create-home --shell /usr/sbin/nologin idealens-auth
fi
install -d -o root -g idealens-auth -m 0750 /etc/idealens
install -d -o root -g root -m 0755 /opt/idealens
python3 - "$source_dir" "$CHROMA_AUTH_KEY_FILE" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from chroma_auth import load_key_hashes
load_key_hashes(Path(sys.argv[2]))
PY
install -o root -g idealens-auth -m 0640 "$CHROMA_AUTH_KEY_FILE" /etc/idealens/chroma-key-hashes.json
install -o root -g root -m 0644 "$source_dir/chroma_auth.py" /opt/idealens/chroma_auth.py
install -o root -g root -m 0644 "$source_dir/idealens-chroma-auth.service" /etc/systemd/system/idealens-chroma-auth.service
printf '%s\n' 'CHROMA_AUTH_KEY_FILE=/etc/idealens/chroma-key-hashes.json' > /etc/idealens/chroma-auth.env
chmod 0640 /etc/idealens/chroma-auth.env
printf 'CHROMA_PUBLIC_HOST=%s\n' "$CHROMA_PUBLIC_HOST" > /etc/idealens/chroma-public.env
chmod 0644 /etc/idealens/chroma-public.env
install -o root -g root -m 0644 "$source_dir/Caddyfile.chroma" /etc/caddy/Caddyfile
install -d -m 0755 /etc/systemd/system/caddy.service.d
printf '%s\n' '[Service]' 'EnvironmentFile=/etc/idealens/chroma-public.env' > /etc/systemd/system/caddy.service.d/idealens.conf
env CHROMA_PUBLIC_HOST="$CHROMA_PUBLIC_HOST" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl daemon-reload
systemctl enable --now idealens-chroma-auth
systemctl enable caddy
echo "Authentication ready. Start Caddy after reviewing HTTPS ingress settings."
