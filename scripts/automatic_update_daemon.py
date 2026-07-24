from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = PROJECT_ROOT / "outputs" / "automatic_update_status.json"
LOG_PATH = PROJECT_ROOT / "outputs" / "automatic_update_task.log"
SCHEDULER_STATUS_PATH = PROJECT_ROOT / "outputs" / "automatic_scheduler_status.json"
SCHEDULE_HOUR = 3


def last_success() -> datetime | None:
    if not STATUS_PATH.exists():
        return None
    try:
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        if status.get("state") != "success" or not status.get("finished_at"):
            return None
        return datetime.fromisoformat(status["finished_at"])
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def due_time(now: datetime) -> datetime:
    today = now.replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    success = last_success()
    if now < today:
        return today
    if success and success >= today:
        return today + timedelta(days=1)
    return now


def run_update() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().astimezone().isoformat()}] Starting daily automatic update\n")
        log.flush()
        result = subprocess.run(
            [
                sys.executable,
                "scripts/update_pipeline.py",
                "--max-pages",
                "200",
                "--depth",
                "1",
                "--max-pages-per-seed",
                "12",
                "--sync-ragflow",
            ],
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.write(f"[{datetime.now().astimezone().isoformat()}] Finished with exit code {result.returncode}\n")


def write_scheduler_status(target: datetime, state: str = "waiting") -> None:
    data = {
        "state": state,
        "pid": os.getpid(),
        "schedule": "每日 03:00",
        "next_run_at": target.isoformat(timespec="seconds"),
        "heartbeat_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    temporary = SCHEDULER_STATUS_PATH.with_suffix(".tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SCHEDULER_STATUS_PATH)


def main() -> None:
    while True:
        now = datetime.now().astimezone()
        target = due_time(now)
        write_scheduler_status(target)
        wait_seconds = (target - now).total_seconds()
        if wait_seconds <= 0:
            write_scheduler_status(target, "running")
            run_update()
            time.sleep(60)
            continue
        time.sleep(min(wait_seconds, 300))


if __name__ == "__main__":
    main()
