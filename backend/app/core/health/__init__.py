"""
Health Check Module - OpenCLAW health monitoring converted to Python.

Provides callable Python functions for:
- Gateway health monitoring (crashes, stuck locks, disconnections)
- Unanswered message scanning
- Missed cron detection
- Daily statistics
"""

from .health_checker import (
    HealthChecker,
    HealthCheckerConfig,
    HealthResult,
    HealthIssue,
    check_gateway_health,
)
from .unanswered_checker import (
    UnansweredChecker,
    UnansweredCheckerConfig,
    UnansweredSession,
    check_unanswered_sessions,
)
from .missed_crons_checker import (
    MissedCronsChecker,
    MissedCronsConfig,
    CronJobStatus,
    check_missed_crons,
    trigger_cron_job,
)
from .daily_stats import (
    DailyStats,
    DailyStatsConfig,
    get_daily_stats,
)

__all__ = [
    # health_checker
    "HealthChecker",
    "HealthCheckerConfig",
    "HealthResult",
    "HealthIssue",
    "check_gateway_health",
    # unanswered_checker
    "UnansweredChecker",
    "UnansweredCheckerConfig",
    "UnansweredSession",
    "check_unanswered_sessions",
    # missed_crons_checker
    "MissedCronsChecker",
    "MissedCronsConfig",
    "CronJobStatus",
    "check_missed_crons",
    "trigger_cron_job",
    # daily_stats
    "DailyStats",
    "DailyStatsConfig",
    "get_daily_stats",
]
