"""
Missed Crons Checker - verifies critical cron jobs ran today.

Converted from check-missed-crons.sh:
- Queries cron API to check job run history
- Verifies each critical job has executed today
- Optionally triggers missed jobs (--run)
- Supports JSON output

Integration: called by Curator (scheduled) and Heartbeat (periodic).
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.core.notification import NotificationManager

DEFAULT_OPENCLAW_DIR = Path.home() / ".openclaw"
DEFAULT_GATEWAY_PORT = 18789

# Critical job definitions: (name, job_id)
DEFAULT_CRITICAL_JOBS: list[tuple[str, str]] = [
    ("xiaohongshu-publish", "6b0d101b-fbd9-49ca-b580-5ce3cf527a06"),
    ("yingshi-taifeng-report", "12144d92-ccc2-40a5-a924-e776f80f5e67"),
    ("moltbook-report", "2c2668dd-b985-4ed0-ba99-147e7781e3fd"),
]


class JobStatus(str, Enum):
    OK = "ok"
    MISSED = "missed"
    ERROR = "error"


@dataclass(frozen=True)
class CronJobStatus:
    """Status of a single cron job."""
    name: str
    job_id: str
    status: JobStatus
    last_run_ms: Optional[int] = None


@dataclass
class MissedCronsConfig:
    """Configuration for missed crons checker."""
    openclaw_dir: Path = DEFAULT_OPENCLAW_DIR
    gateway_port: int = DEFAULT_GATEWAY_PORT
    critical_jobs: Optional[list[tuple[str, str]]] = None
    log_to_file: bool = True


@dataclass
class MissedCronsResult:
    """Result of missed crons check."""
    ok_count: int
    missed_count: int
    error_count: int
    jobs: tuple[CronJobStatus, ...]
    all_ok: bool


class MissedCronsChecker:
    """
    Check if critical cron jobs have run today.

    Queries the Gateway cron API to verify each job's last run time
    and reports any that haven't executed today.
    """

    def __init__(self, config: Optional[MissedCronsConfig] = None) -> None:
        self.config = config or MissedCronsConfig()
        if self.config.critical_jobs is None:
            self.config.critical_jobs = DEFAULT_CRITICAL_JOBS.copy()

    def set_notification_manager(self, nm: "NotificationManager") -> None:
        """Inject NotificationManager for proactive alerting."""
        self._notification_manager: "NotificationManager" = nm

    async def check(self, run_missed: bool = False) -> MissedCronsResult:
        """
        Check critical cron jobs.

        Args:
            run_missed: If True, trigger execution of missed jobs.

        Returns:
            MissedCronsResult with per-job status.
        """
        # Check gateway is running
        if not self._gateway_health():
            return MissedCronsResult(
                ok_count=0,
                missed_count=0,
                error_count=len(self.config.critical_jobs),
                jobs=tuple(
                    CronJobStatus(name=name, job_id=job_id, status=JobStatus.ERROR)
                    for name, job_id in self.config.critical_jobs
                ),
                all_ok=False,
            )

        today_start_ms = self._today_start_ms()
        job_statuses: list[CronJobStatus] = []
        ok_count = 0
        missed_count = 0
        error_count = 0
        missed_job_ids: list[str] = []

        for name, job_id in self.config.critical_jobs:
            status, last_run = self._check_job_today(job_id, today_start_ms)

            job_statuses.append(CronJobStatus(
                name=name,
                job_id=job_id,
                status=status,
                last_run_ms=last_run,
            ))

            if status == JobStatus.OK:
                ok_count += 1
            elif status == JobStatus.MISSED:
                missed_count += 1
                missed_job_ids.append(job_id)
            else:
                error_count += 1

        # Trigger missed jobs if requested
        if run_missed and missed_job_ids:
            for job_id in missed_job_ids:
                self._trigger_job(job_id)

        # Log result
        if self.config.log_to_file:
            self._log_check(ok_count, missed_count, error_count)

        result = MissedCronsResult(
            ok_count=ok_count,
            missed_count=missed_count,
            error_count=error_count,
            jobs=tuple(job_statuses),
            all_ok=missed_count == 0 and error_count == 0,
        )

        # Dispatch notification if there are missed or error jobs
        if (missed_count > 0 or error_count > 0) and hasattr(self, "_notification_manager"):
            from app.core.notification.events import NotificationEvent, NotificationSeverity

            missed_jobs = [j.name for j in job_statuses if j.status == JobStatus.MISSED]
            error_jobs = [j.name for j in job_statuses if j.status == JobStatus.ERROR]

            body_parts = []
            if missed_jobs:
                body_parts.append(f"未执行：{', '.join(missed_jobs)}")
            if error_jobs:
                body_parts.append(f"检查失败：{', '.join(error_jobs)}")

            notification = NotificationEvent(
                severity=NotificationSeverity.CRITICAL if error_count > 0 else NotificationSeverity.WARNING,
                source="missed_crons",
                title="有关键 Cron 任务漏跑",
                body="\n".join(body_parts),
            )
            await self._notification_manager.dispatch(notification)

        return result

    # ------------------------------------------------------------------
    # Gateway communication
    # ------------------------------------------------------------------

    def _gateway_health(self) -> bool:
        """Check if gateway is responding."""
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.config.gateway_port}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _get_token(self) -> Optional[str]:
        """Read gateway token from openclaw.json."""
        config_file = self.config.openclaw_dir / "openclaw.json"
        if not config_file.exists():
            return None
        try:
            data = json.loads(config_file.read_text())
            return data.get("token")
        except Exception:
            return None

    def _call_cron_api(self, action: str, job_id: Optional[str] = None) -> Optional[dict]:
        """Call the cron API with given action and optional job_id."""
        token = self._get_token()
        if not token:
            logger.warning("No gateway token found")
            return None

        url = f"http://127.0.0.1:{self.config.gateway_port}/api/cron"
        payload: dict = {"action": action}
        if job_id:
            payload["jobId"] = job_id

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning(f"Cron API error for action={action}: {e.code}")
            return None
        except Exception as e:
            logger.warning(f"Cron API error for action={action}: {e}")
            return None

    def _check_job_today(self, job_id: str, today_start_ms: int) -> tuple[JobStatus, Optional[int]]:
        """
        Check if a job has run today.

        Returns:
            (status, last_run_ms)
        """
        result = self._call_cron_api("runs", job_id)
        if result is None or "error" in result:
            return JobStatus.ERROR, None

        runs = result.get("runs", [])
        if not runs:
            return JobStatus.MISSED, None

        # Find the most recent run
        last_run_ms = 0
        for run in runs:
            started = run.get("startedAtMs", 0)
            if started > last_run_ms:
                last_run_ms = started

        if last_run_ms >= today_start_ms:
            return JobStatus.OK, last_run_ms
        return JobStatus.MISSED, last_run_ms

    def _trigger_job(self, job_id: str) -> bool:
        """Trigger a job to run immediately."""
        result = self._call_cron_api("run", job_id)
        if result is not None:
            logger.info(f"Triggered job: {job_id}")
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today_start_ms() -> int:
        """Get today's start timestamp in milliseconds UTC."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(today_start.timestamp() * 1000)

    def _log_check(self, ok: int, missed: int, errors: int) -> None:
        """Log check results to file."""
        log_dir = self.config.openclaw_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "cron-check.log"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] Checked: ok={ok} missed={missed} error={errors}\n"
        try:
            log_file.write_text(log_file.read_text() + entry, append=True)
        except Exception as e:
            logger.warning(f"Could not write cron check log: {e}")

    def format_json(self, result: MissedCronsResult) -> str:
        """Format result as JSON string."""
        jobs_data = [
            {
                "name": j.name,
                "status": j.status.value,
                "last_run_ms": j.last_run_ms,
            }
            for j in result.jobs
        ]
        return json.dumps({
            "ok": result.ok_count,
            "missed": result.missed_count,
            "error": result.error_count,
            "jobs": jobs_data,
        }, ensure_ascii=False, indent=2)

    def format_text(self, result: MissedCronsResult) -> str:
        """Format result as human-readable text."""
        lines = [f"Cron Check ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')})", ""]

        status_symbols = {
            JobStatus.OK: "OK",
            JobStatus.MISSED: "MISSED",
            JobStatus.ERROR: "ERROR",
        }

        for job in result.jobs:
            symbol = status_symbols[job.status]
            msg = f"[{symbol}] {job.name}"
            if job.status == JobStatus.MISSED:
                msg += " - not executed today"
            elif job.status == JobStatus.ERROR:
                msg += " - could not check"
            lines.append(msg)

        lines.append("")
        if result.all_ok:
            lines.append("All critical jobs executed today")
        else:
            lines.append(f"{result.missed_count} job(s) not executed today")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Convenience functions
# ------------------------------------------------------------------

async def check_missed_crons(
    openclaw_dir: Optional[Path] = None,
    gateway_port: int = DEFAULT_GATEWAY_PORT,
    critical_jobs: Optional[list[tuple[str, str]]] = None,
    run_missed: bool = False,
    output_format: str = "text",  # "text" or "json"
) -> MissedCronsResult | str:
    """
    Check if critical cron jobs have run today.

    Args:
        openclaw_dir: Path to OpenCLAW directory (default: ~/.openclaw)
        gateway_port: Gateway API port (default: 18789)
        critical_jobs: List of (name, job_id) tuples to check
        run_missed: Trigger missed jobs immediately
        output_format: "text" or "json"

    Returns:
        MissedCronsResult or formatted string
    """
    config = MissedCronsConfig(
        openclaw_dir=openclaw_dir or DEFAULT_OPENCLAW_DIR,
        gateway_port=gateway_port,
        critical_jobs=critical_jobs,
    )
    checker = MissedCronsChecker(config)
    result = await checker.check(run_missed=run_missed)

    if output_format == "json":
        return checker.format_json(result)
    return checker.format_text(result)


def trigger_cron_job(
    job_id: str,
    openclaw_dir: Optional[Path] = None,
    gateway_port: int = DEFAULT_GATEWAY_PORT,
) -> bool:
    """
    Trigger a specific cron job to run immediately.

    Args:
        job_id: The job UUID to trigger
        openclaw_dir: Path to OpenCLAW directory (default: ~/.openclaw)
        gateway_port: Gateway API port (default: 18789)

    Returns:
        True if triggered successfully, False otherwise
    """
    config = MissedCronsConfig(
        openclaw_dir=openclaw_dir or DEFAULT_OPENCLAW_DIR,
        gateway_port=gateway_port,
    )
    checker = MissedCronsChecker(config)
    return checker._trigger_job(job_id)
