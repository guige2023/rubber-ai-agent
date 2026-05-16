"""
Gateway Health Checker - monitors OpenCLAW Gateway health.

Converted from gateway-health-check.sh:
- Detects multiple gateway processes (keeps latest PID)
- Cleans stale session lock files
- Detects gateway crashes and auto-restarts
- Detects stuck queues
- Detects Feishu WebSocket disconnections
- Auto-recovery with retry logic

Integration: called by Curator (scheduled) and Heartbeat (periodic).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.core.notification import NotificationManager

# Default OpenCLAW directory (can be overridden via config)
DEFAULT_OPENCLAW_DIR = Path.home() / ".openclaw"
DEFAULT_GATEWAY_PORT = 18789
DEFAULT_LOCK_TIMEOUT_MINUTES = 5
DEFAULT_LOCK_FORCE_REMOVE_MINUTES = 15
DEFAULT_QUEUE_STUCK_MINUTES = 3
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_INTERVAL_SECONDS = 120


class IssueSeverity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class HealthIssue:
    """Represents a detected health issue."""
    code: str
    severity: IssueSeverity
    message: str
    detail: Optional[str] = None


@dataclass(frozen=True)
class HealthResult:
    """Result of a health check run."""
    timestamp: str
    issues_fixed: int
    issues_detected: int
    issues: tuple[HealthIssue, ...]
    all_ok: bool


@dataclass
class HealthCheckerConfig:
    """Configuration for health checker behavior."""
    openclaw_dir: Path = DEFAULT_OPENCLAW_DIR
    gateway_port: int = DEFAULT_GATEWAY_PORT
    lock_timeout_minutes: int = DEFAULT_LOCK_TIMEOUT_MINUTES
    lock_force_remove_minutes: int = DEFAULT_LOCK_FORCE_REMOVE_MINUTES
    queue_stuck_minutes: int = DEFAULT_QUEUE_STUCK_MINUTES
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_interval_seconds: int = DEFAULT_RETRY_INTERVAL_SECONDS
    log_to_file: bool = True
    retry_state_file: Optional[Path] = None

    def __post_init__(self) -> None:
        if self.retry_state_file is None:
            self.retry_state_file = self.openclaw_dir / "retry-state.json"


class HealthChecker:
    """
    OpenCLAW Gateway health monitor.

    Performs the following checks:
    1. Gateway process running
    2. Multiple gateway processes (deduplication)
    3. Stale session lock files
    4. Stuck thinking sessions
    5. Session state issues
    6. Stuck dispatch detection
    7. Queue stuck detection
    8. Provider errors and auto-retry
    9. Feishu WebSocket connection

    Results are logged and returned as a HealthResult.
    """

    def __init__(self, config: Optional[HealthCheckerConfig] = None) -> None:
        self.config = config or HealthCheckerConfig()
        self._issues_fixed = 0
        self._issues_detected = 0
        self._issues: list[HealthIssue] = []

    def set_notification_manager(self, nm: "NotificationManager") -> None:
        """Inject NotificationManager for proactive alerting."""
        self._notification_manager: "NotificationManager" = nm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_health_check(self) -> HealthResult:
        """
        Run all health checks.

        Returns:
            HealthResult with all detected issues and fixes applied.
        """
        self._issues_fixed = 0
        self._issues_detected = 0
        self._issues = []

        timestamp = datetime.now(timezone.utc).isoformat()
        logger.info(f"[HealthCheck] Starting health check at {timestamp}")

        # Run all checks
        self._check_gateway_running()
        self._check_multiple_gateways()
        await self._check_stale_locks()
        await self._check_stuck_thinking_sessions()
        await self._check_session_states()
        await self._check_stuck_dispatch()
        await self._check_queue_stuck()
        await self._check_provider_errors()
        await self._check_feishu_connection()

        # Log results
        self._log_health_check(timestamp)

        result = HealthResult(
            timestamp=timestamp,
            issues_fixed=self._issues_fixed,
            issues_detected=self._issues_detected,
            issues=tuple(self._issues),
            all_ok=len(self._issues) == 0,
        )

        # Dispatch notification for critical issues
        if not result.all_ok and hasattr(self, "_notification_manager"):
            from app.core.notification.events import NotificationEvent, NotificationSeverity

            # Group issues by severity
            critical_issues = [i for i in self._issues if i.severity == IssueSeverity.ERROR]
            warning_issues = [i for i in self._issues if i.severity == IssueSeverity.WARNING]

            if critical_issues:
                body = "\n".join(f"• [{i.code}] {i.message}" for i in critical_issues[:5])
                notification = NotificationEvent(
                    severity=NotificationSeverity.CRITICAL,
                    source="health_checker",
                    title="Gateway 健康检查发现严重问题",
                    body=body,
                )
                await self._notification_manager.dispatch(notification)

            if warning_issues:
                body = "\n".join(f"• [{i.code}] {i.message}" for i in warning_issues[:5])
                notification = NotificationEvent(
                    severity=NotificationSeverity.WARNING,
                    source="health_checker",
                    title="Gateway 健康检查发现警告",
                    body=body,
                )
                await self._notification_manager.dispatch(notification)

        return result

    def get_status(self) -> dict:
        """Get current health checker status (sync)."""
        return {
            "openclaw_dir": str(self.config.openclaw_dir),
            "gateway_port": self.config.gateway_port,
            "config": {
                "lock_timeout_minutes": self.config.lock_timeout_minutes,
                "lock_force_remove_minutes": self.config.lock_force_remove_minutes,
                "queue_stuck_minutes": self.config.queue_stuck_minutes,
                "max_retries": self.config.max_retries,
            },
        }

    # ------------------------------------------------------------------
    # Check 1: Gateway running
    # ------------------------------------------------------------------

    def _check_gateway_running(self) -> None:
        """Check if at least one gateway process is running."""
        pids = self._get_gateway_pids()
        if pids:
            logger.debug(f"Gateway running with PIDs: {pids}")
            return

        # Gateway not running - try to start it
        self._add_issue(
            code="GATEWAY_NOT_RUNNING",
            severity=IssueSeverity.ERROR,
            message="Gateway not running, attempting to start",
        )
        self._issues_detected += 1
        self._attempt_start_gateway()

    def _attempt_start_gateway(self) -> bool:
        """Attempt to start the gateway."""
        try:
            result = subprocess.run(
                ["openclaw", "gateway", "start"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and self._get_gateway_pids():
                self._add_issue(
                    code="GATEWAY_STARTED",
                    severity=IssueSeverity.OK,
                    message="Gateway started successfully",
                )
                self._send_wake_notification(
                    "[Gateway 重启通知] Gateway 刚被健康检查脚本重启。"
                    "请：1) 汇报重启情况 2) 检查之前的任务状态 3) 继续推进未完成的任务"
                )
                return True
            else:
                self._add_issue(
                    code="GATEWAY_START_FAILED",
                    severity=IssueSeverity.ERROR,
                    message=f"Failed to start gateway: {result.stderr[:200]}",
                )
                return False
        except Exception as e:
            self._add_issue(
                code="GATEWAY_START_EXCEPTION",
                severity=IssueSeverity.ERROR,
                message=f"Exception starting gateway: {e}",
            )
            return False

    # ------------------------------------------------------------------
    # Check 2: Multiple gateways
    # ------------------------------------------------------------------

    def _check_multiple_gateways(self) -> None:
        """Detect multiple gateway processes, kill old ones."""
        pids = self._get_gateway_pids()
        if not pids:
            return
        if len(pids) <= 1:
            return

        # Keep the newest (largest PID), kill the rest
        newest = max(pids)
        for pid in pids:
            if pid != newest:
                try:
                    os.kill(pid, 9)
                    self._add_issue(
                        code="OLD_GATEWAY_KILLED",
                        severity=IssueSeverity.WARNING,
                        message=f"Killed old gateway process: {pid}",
                    )
                    self._issues_fixed += 1
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Check 3: Stale locks
    # ------------------------------------------------------------------

    async def _check_stale_locks(self) -> None:
        """Remove stale session lock files."""
        agents_dir = self.config.openclaw_dir / "agents"
        if not agents_dir.exists():
            return

        now_ts = datetime.now(timezone.utc).timestamp()
        stale_count = 0

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            sessions_dir = agent_dir / "sessions"
            if not sessions_dir.exists():
                continue
            for lock_file in sessions_dir.glob("*.lock"):
                try:
                    mtime = lock_file.stat().st_mtime
                    age_minutes = int((now_ts - mtime) / 60)
                    if age_minutes <= self.config.lock_timeout_minutes:
                        continue

                    lock_pid = self._read_lock_pid(lock_file)
                    should_remove = False

                    if lock_pid and not self._is_pid_running(lock_pid):
                        should_remove = True
                        reason = f"pid {lock_pid} not running"
                    elif age_minutes > self.config.lock_force_remove_minutes:
                        should_remove = True
                        reason = f"age {age_minutes}min > {self.config.lock_force_remove_minutes}min"

                    if should_remove:
                        lock_file.unlink(missing_ok=True)
                        stale_count += 1
                        self._issues_fixed += 1
                        self._add_issue(
                            code="STALE_LOCK_REMOVED",
                            severity=IssueSeverity.WARNING,
                            message=f"Removed stale lock: {lock_file.name} ({reason})",
                        )
                except Exception as e:
                    logger.debug(f"Error checking lock {lock_file}: {e}")

        if stale_count > 0:
            self._issues_detected += stale_count

    @staticmethod
    def _read_lock_pid(lock_file: Path) -> Optional[int]:
        """Extract PID from a lock file."""
        try:
            content = lock_file.read_text()
            import re
            match = re.search(r'"pid":\s*(\d+)', content)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return None

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        """Check if a process with given PID is running."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Check 4: Stuck thinking sessions
    # ------------------------------------------------------------------

    async def _check_stuck_thinking_sessions(self) -> None:
        """Remove sessions that are stuck in thinking-only state."""
        agents_dir = self.config.openclaw_dir / "agents"
        if not agents_dir.exists():
            return

        now_ts = datetime.now(timezone.utc).timestamp()
        stuck_count = 0

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            sessions_dir = agent_dir / "sessions"
            if not sessions_dir.exists():
                continue
            for session_file in sessions_dir.glob("*.jsonl"):
                # Skip if has active lock
                if session_file.with_suffix(".lock").exists():
                    continue

                try:
                    is_stuck, _ = self._detect_stuck_session(session_file)
                    if not is_stuck:
                        continue

                    mtime = session_file.stat().st_mtime
                    age_minutes = int((now_ts - mtime) / 60)
                    if age_minutes <= 5:
                        continue  # Still potentially active

                    session_file.unlink(missing_ok=True)
                    stuck_count += 1
                    self._issues_fixed += 1
                    self._add_issue(
                        code="STUCK_SESSION_REMOVED",
                        severity=IssueSeverity.WARNING,
                        message=f"Removed thinking-only stuck session: {session_file.name}",
                        detail=f"age={age_minutes}min",
                    )
                except Exception as e:
                    logger.debug(f"Error checking session {session_file}: {e}")

        if stuck_count > 0:
            self._issues_detected += stuck_count

    @staticmethod
    def _detect_stuck_session(session_file: Path) -> tuple[bool, Optional[str]]:
        """
        Detect if a session is stuck.

        Returns:
            (is_stuck, reason)
        """
        try:
            lines = session_file.read_text().strip().split("\n")
            if not lines:
                return False, None
            last_line = lines[-1]
            data = json.loads(last_line)

            msg = data.get("message", {})
            role = msg.get("role", "")
            content = msg.get("content", [])

            if role == "assistant":
                types = [c.get("type") for c in content if isinstance(c, dict)]
                if types == ["thinking"]:
                    return True, "assistant thinking-only"
            elif role == "toolResult":
                text_parts = [
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                combined = " ".join(text_parts)
                if "synthetic error" in combined or "missing tool result" in combined:
                    return True, "toolResult synthetic error"

            return False, None
        except Exception:
            return False, None

    # ------------------------------------------------------------------
    # Check 5: Session states
    # ------------------------------------------------------------------

    async def _check_session_states(self) -> None:
        """Run fix-sessions.py if present."""
        fix_script = self.config.openclaw_dir / "workspace" / "scripts" / "fix-sessions.py"
        if not fix_script.exists():
            return

        try:
            result = subprocess.run(
                ["python3", str(fix_script)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.config.openclaw_dir),
            )
            if result.returncode != 0:
                self._add_issue(
                    code="SESSION_FIX_FAILED",
                    severity=IssueSeverity.WARNING,
                    message=f"fix-sessions.py failed: {result.stderr[:200]}",
                )
                self._issues_detected += 1
        except Exception as e:
            logger.debug(f"Could not run fix-sessions.py: {e}")

    # ------------------------------------------------------------------
    # Check 6: Stuck dispatch
    # ------------------------------------------------------------------

    async def _check_stuck_dispatch(self) -> None:
        """Detect sessions with stuck dispatch (dispatched but no LLM call)."""
        detect_script = self.config.openclaw_dir / "workspace" / "scripts" / "detect-stuck-dispatch.py"
        if not detect_script.exists():
            return

        # Check rate limit: don't restart if done recently
        stuck_state_file = self.config.openclaw_dir / "stuck-dispatch-state.json"
        if stuck_state_file.exists():
            try:
                state = json.loads(stuck_state_file.read_text())
                last_restart = state.get("lastRestart", 0)
                elapsed = datetime.now(timezone.utc).timestamp() - last_restart
                if elapsed < 1800:  # 30 minutes
                    logger.debug("Stuck dispatch check skipped: recent restart")
                    return
            except Exception:
                pass

        try:
            result = subprocess.run(
                ["python3", str(detect_script)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return  # No stuck sessions

            stuck_sessions = result.stdout.strip()
            if not stuck_sessions:
                return

            self._add_issue(
                code="STUCK_DISPATCH_DETECTED",
                severity=IssueSeverity.ERROR,
                message=f"Stuck dispatch detected for sessions: {stuck_sessions}",
            )
            self._issues_detected += 1

            # Save session states
            save_script = self.config.openclaw_dir / "workspace" / "scripts" / "save-session-states.py"
            recovery_file = None
            if save_script.exists():
                try:
                    save_result = subprocess.run(
                        ["python3", str(save_script)] + stuck_sessions.split(),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    recovery_file = save_result.stdout.strip()
                except Exception:
                    pass

            # Update state
            state_data = {
                "lastRestart": int(datetime.now(timezone.utc).timestamp()),
                "stuckSessions": stuck_sessions,
            }
            stuck_state_file.write_text(json.dumps(state_data))

            # Restart gateway
            self._restart_gateway()

            # Send notification
            notification = (
                f"[Stuck Dispatch 自动恢复] 检测到 session dispatch 卡住，"
                f"已自动重启 Gateway。卡住的 session：{stuck_sessions}"
            )
            if recovery_file:
                notification += f"。恢复文件：{recovery_file}"
            self._send_wake_notification(notification)

        except Exception as e:
            logger.debug(f"Stuck dispatch check error: {e}")

    # ------------------------------------------------------------------
    # Check 7: Queue stuck
    # ------------------------------------------------------------------

    async def _check_queue_stuck(self) -> None:
        """Check if message queue is stuck."""
        today_log = self._get_today_log()
        if today_log is None or not today_log.exists():
            return

        try:
            content = today_log.read_text()
            lines = content.split("\n")
            now_ts = datetime.now(timezone.utc).timestamp()
            stuck_threshold = self.config.queue_stuck_minutes * 60

            # Find dequeue without corresponding done/error
            dequeue_pattern = 'lane dequeue'
            done_pattern = 'lane task done'
            error_pattern = 'lane task error'

            stuck_lanes: set[str] = set()
            recent_lines = [l for l in lines if dequeue_pattern in l or done_pattern in l or error_pattern in l]
            recent_lines = recent_lines[-2000:]  # Last 2000 lines

            # Parse dequeue lines with timestamps
            dequeue_events: list[tuple[str, float, str]] = []  # (timestamp_str, epoch, lane)
            for line in recent_lines:
                if dequeue_pattern not in line:
                    continue
                import re
                ts_match = re.search(r'"date":"([^"]+)"', line)
                lane_match = re.search(r'lane=([^ ]+)', line)
                if ts_match and lane_match:
                    ts_str = ts_match.group(1).split(".")[0]
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
                        dt = dt.replace(tzinfo=timezone.utc)
                        epoch = dt.timestamp()
                        lane = lane_match.group(1)
                        dequeue_events.append((ts_str, epoch, lane))
                    except Exception:
                        pass

            for ts_str, event_epoch, lane in dequeue_events:
                age_seconds = now_ts - event_epoch
                if age_seconds > 600:  # Older than 10 min
                    continue
                if age_seconds < stuck_threshold:
                    continue

                # Check if done/error exists after this dequeue
                done_found = False
                for l2 in recent_lines:
                    if (done_pattern in l2 or error_pattern in l2) and lane in l2:
                        done_ts_match = re.search(r'"date":"([^"]+)"', l2)
                        if done_ts_match:
                            done_ts = done_ts_match.group(1).split(".")[0]
                            try:
                                from datetime import datetime
                                dt2 = datetime.strptime(done_ts, "%Y-%m-%dT%H:%M:%S")
                                dt2 = dt2.replace(tzinfo=timezone.utc)
                                if dt2.timestamp() > event_epoch:
                                    done_found = True
                                    break
                            except Exception:
                                pass

                if not done_found and age_seconds > stuck_threshold:
                    stuck_lanes.add(lane)

            if stuck_lanes:
                self._add_issue(
                    code="QUEUE_STUCK",
                    severity=IssueSeverity.ERROR,
                    message=f"Queue stuck for lanes: {', '.join(stuck_lanes)}",
                )
                self._issues_detected += 1
                self._restart_gateway()
                self._send_wake_notification(
                    f"[队列卡住自动恢复] 检测到以下 session 队列卡住超过 "
                    f"{self.config.queue_stuck_minutes} 分钟，已自动重启 Gateway：{', '.join(stuck_lanes)}"
                )

        except Exception as e:
            logger.debug(f"Queue stuck check error: {e}")

    # ------------------------------------------------------------------
    # Check 8: Provider errors
    # ------------------------------------------------------------------

    async def _check_provider_errors(self) -> None:
        """Check for recent provider errors and trigger retry."""
        today_log = self._get_today_log()
        if today_log is None or not today_log.exists():
            return

        try:
            content = today_log.read_text()
            lines = content.split("\n")

            # Find recent provider errors (last 20 lines)
            error_lines = [
                l for l in lines
                if "All models failed" in l or "FailoverError" in l
            ][-20:]

            if not error_lines:
                # No errors - clear retry state
                rs = self.config.retry_state_file
                if rs and rs.exists():
                    rs.unlink(missing_ok=True)
                return

            last_error_line = error_lines[-1]
            import re
            ts_match = re.search(r'"date":"([^"]+)"', last_error_line)
            if not ts_match:
                return

            ts_str = ts_str_full = ts_match.group(1).split(".")[0]
            from datetime import datetime
            try:
                dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
                age_seconds = datetime.now(timezone.utc).timestamp() - dt.timestamp()
                if age_seconds > 300:  # Older than 5 min
                    return
            except Exception:
                return

            # Extract failed lane
            lane_match = re.search(r'lane=([^ ]+)', last_error_line)
            failed_lane = lane_match.group(1) if lane_match else None
            if not failed_lane:
                return

            # Check/update retry state
            rs = self.config.retry_state_file
            retry_count = 0
            last_retry_time = 0
            if rs and rs.exists():
                try:
                    state = json.loads(rs.read_text())
                    retry_count = state.get("count", 0)
                    last_retry_time = state.get("lastRetry", 0)
                    if state.get("lane") != failed_lane:
                        retry_count = 0
                        last_retry_time = 0
                except Exception:
                    pass

            if retry_count >= self.config.max_retries:
                return

            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - last_retry_time < self.config.retry_interval_seconds:
                return

            # Increment and save retry state
            retry_count += 1
            state_data = {
                "lane": failed_lane,
                "count": retry_count,
                "lastRetry": int(now_ts),
                "lastError": ts_str_full,
            }
            if rs:
                rs.write_text(json.dumps(state_data))

            self._send_wake_notification(
                f"[自动重试] Provider 错误恢复检查 (第 {retry_count} 次)。"
                f"失败的 session: {failed_lane}"
            )

        except Exception as e:
            logger.debug(f"Provider error check error: {e}")

    # ------------------------------------------------------------------
    # Check 9: Feishu connection
    # ------------------------------------------------------------------

    async def _check_feishu_connection(self) -> None:
        """Check Feishu WebSocket connection via gateway log."""
        gateway_log = self.config.openclaw_dir / "logs" / "gateway.log"
        if not gateway_log.exists():
            return

        try:
            content = gateway_log.read_text()
            lines = content.split("\n")
            recent_lines = lines[-100:]

            # Check for recent disconnects without reconnect
            disconnected = any(
                "abort signal received" in l or "WebSocket" in l and "closed" in l or "connection" in l and "lost" in l
                for l in recent_lines
            )
            if not disconnected:
                return

            reconnected = any("WebSocket client started" in l for l in recent_lines[-50:])
            if not reconnected:
                self._add_issue(
                    code="FEISHU_DISCONNECTED",
                    severity=IssueSeverity.WARNING,
                    message="Feishu WebSocket connection may be down",
                )
                self._issues_detected += 1
                self._restart_gateway()

        except Exception as e:
            logger.debug(f"Feishu connection check error: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_gateway_pids(self) -> list[int]:
        """Get PIDs of running gateway processes."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            pids = []
            for line in result.stdout.split("\n"):
                if "openclaw-gateway" in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pids.append(int(parts[1]))
                        except ValueError:
                            pass
            return sorted(pids)
        except Exception:
            return []

    def _get_gateway_token(self) -> Optional[str]:
        """Read gateway token from openclaw.json."""
        config_file = self.config.openclaw_dir / "openclaw.json"
        if not config_file.exists():
            return None
        try:
            data = json.loads(config_file.read_text())
            return data.get("token")
        except Exception:
            return None

    def _get_today_log(self) -> Optional[Path]:
        """Get today's OpenCLAW log file path."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = self.config.openclaw_dir / "logs" / f"openclaw-{today}.log"
        if log_path.exists():
            return log_path
        # Fallback: /tmp/openclaw/
        tmp_log = Path(f"/tmp/openclaw/openclaw-{today}.log")
        if tmp_log.exists():
            return tmp_log
        return None

    def _restart_gateway(self) -> None:
        """Restart the gateway process."""
        try:
            subprocess.run(
                ["openclaw", "gateway", "restart"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            logger.warning(f"Gateway restart failed: {e}")

    def _send_wake_notification(self, text: str) -> None:
        """Send a wake notification via gateway API."""
        token = self._get_gateway_token()
        if not token:
            logger.debug("No gateway token, skipping wake notification")
            return

        import urllib.request
        import urllib.error

        url = f"http://127.0.0.1:{self.config.gateway_port}/api/cron/wake"
        data = json.dumps({
            "text": text,
            "mode": "now",
        }).encode("utf-8")

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
                resp.read()
        except Exception as e:
            logger.debug(f"Wake notification failed: {e}")

    def _add_issue(
        self,
        code: str,
        severity: IssueSeverity,
        message: str,
        detail: Optional[str] = None,
    ) -> None:
        """Record an issue."""
        issue = HealthIssue(code=code, severity=severity, message=message, detail=detail)
        self._issues.append(issue)
        logger.info(f"[HealthCheck] {severity.value.upper()} {code}: {message}")

    def _log_health_check(self, timestamp: str) -> None:
        """Write health check result to log file."""
        if not self.config.log_to_file:
            return

        log_dir = self.config.openclaw_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "health-check.log"

        status = "All checks passed" if len(self._issues) == 0 else f"Fixed {self._issues_fixed} issue(s)"
        entry = f"[{timestamp}] {status}\n"
        try:
            log_file.write_text(log_file.read_text() + entry, append=True)
        except Exception as e:
            logger.warning(f"Could not write health log: {e}")


# ------------------------------------------------------------------
# Convenience function for quick health checks
# ------------------------------------------------------------------

async def check_gateway_health(
    openclaw_dir: Optional[Path] = None,
    **kwargs,
) -> HealthResult:
    """
    Run a quick gateway health check.

    Args:
        openclaw_dir: Path to OpenCLAW directory (default: ~/.openclaw)
        **kwargs: Additional config options

    Returns:
        HealthResult with detected issues
    """
    config = HealthCheckerConfig(
        openclaw_dir=openclaw_dir or DEFAULT_OPENCLAW_DIR,
        **kwargs,
    )
    checker = HealthChecker(config)
    return await checker.run_health_check()
