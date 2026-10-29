"""프로세스 내 백그라운드 작업 상태(보고서 흐름·사업기획 자료집 생성)."""

import threading

WORKFLOW_JOBS: dict[str, dict] = {}
WORKFLOW_JOBS_LOCK = threading.Lock()

PLANNER_JOBS: dict[str, dict] = {}
PLANNER_JOBS_LOCK = threading.Lock()
