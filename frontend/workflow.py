"""프로세스 내 백그라운드 보고서 흐름 상태."""

import threading

WORKFLOW_JOBS: dict[str, dict] = {}
WORKFLOW_JOBS_LOCK = threading.Lock()
