#!/bin/bash
# Debian VM에서 Chroma를 설치하고 같은 데이터 폴더로 재시작한다.
set -euo pipefail
exec >> /var/log/idealens-chroma-startup.log 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io curl
systemctl enable --now docker
mkdir -p /srv/idealens/chroma /srv/idealens/backups
if ! docker container inspect idealens-chroma >/dev/null 2>&1; then
    docker run -d --name idealens-chroma --restart unless-stopped \
      --log-opt max-size=10m --log-opt max-file=3 \
      -p 127.0.0.1:8000:8000 \
      -v /srv/idealens/chroma:/data \
      -e CHROMA_PERSIST_PATH=/data \
      -e ANONYMIZED_TELEMETRY=False \
      chromadb/chroma:1.5.9
else
    docker start idealens-chroma
fi
for attempt in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:8000/api/v2/heartbeat; then
        echo "Chroma ready"
        exit 0
    fi
    sleep 2
done
exit 1
