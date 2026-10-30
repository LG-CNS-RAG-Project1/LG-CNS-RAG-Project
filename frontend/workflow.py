"""프로세스 내 백그라운드 보고서 흐름 상태."""

import threading
import time

WORKFLOW_JOBS: dict[str, dict] = {}
WORKFLOW_JOBS_LOCK = threading.Lock()


def prune_finished_jobs():
    """완료 작업은 새로고침 복구용으로 20분, 최대 20건까지만 보관한다."""
    with WORKFLOW_JOBS_LOCK:
        finished = sorted(
            (
                (key, job.setdefault("updated_at", time.monotonic()))
                for key, job in WORKFLOW_JOBS.items()
                if job.get("done")
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        for index, (key, updated) in enumerate(finished):
            if index >= 20 or time.monotonic() - updated > 1200:
                WORKFLOW_JOBS.pop(key, None)
