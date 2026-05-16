from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlmodel import Session as DBSession, select

from app.core.db import get_session
from app.models.database import MessageModel, SessionModel

logger = logging.getLogger(__name__)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SessionManager:
    """Manage persisted chat-session state.

    This manager owns database state for chat sessions, messages, run metadata,
    usage, and memory. It does not build model history or manage browser,
    workspace, schedule, tool, or agent lifecycles.
    """

    @staticmethod
    def session_exists(session_id: str) -> bool:
        with get_session() as db_session:
            return db_session.get(SessionModel, session_id) is not None

    @staticmethod
    def get_recent_sessions(limit: int = 10) -> list[SessionModel]:
        """Return the most recent sessions ordered by updated_at desc."""
        with get_session() as db_session:
            return list(
                db_session.exec(
                    select(SessionModel)
                    .order_by(SessionModel.updated_at.desc())
                    .limit(limit)
                ).all()
            )

    @staticmethod
    def ensure_session(
            session_id: str,
            *,
            title: Optional[str] = None,
            metadata: Optional[dict[str, object]] = None,
    ) -> SessionModel:
        with get_session() as db_session:
            session_obj = db_session.get(SessionModel, session_id)
            if session_obj:
                changed = False
                if title is not None and not session_obj.title:
                    session_obj.title = title
                    changed = True
                if metadata:
                    next_metadata = dict(session_obj.metadata_ or {})
                    next_metadata.update(metadata)
                    session_obj.metadata_ = next_metadata
                    changed = True
                if changed:
                    session_obj.updated_at = datetime.now(timezone.utc)
                    db_session.add(session_obj)
                    db_session.commit()
                    db_session.refresh(session_obj)
                return session_obj

            session_obj = SessionModel(
                id=session_id,
                title=title or "",
                metadata_=dict(metadata or {}),
            )
            db_session.add(session_obj)
            db_session.commit()
            db_session.refresh(session_obj)
            return session_obj

    @staticmethod
    def append_user_message(
            *,
            session_id: str,
            content: str,
            run_id: str,
            token_estimate: int,
    ) -> MessageModel:
        with get_session() as db_session:
            message = MessageModel(
                session_id=session_id,
                role="user",
                content=content,
                type="text",
                token_estimate=token_estimate,
                metadata_={
                    "run": {
                        "id": run_id,
                        "status": "pending",
                    }
                },
            )
            db_session.add(message)
            db_session.commit()
            db_session.refresh(message)
            return message

    @staticmethod
    def record_agent_run_success(
            *,
            user_message_id: Optional[str],
            session_id: str,
            run_id: str,
            content: str,
            token_estimate: int,
            parts: Optional[list[dict[str, object]]] = None,
            usage: Optional[dict[str, int]] = None,
            model: Optional[dict[str, object]] = None,
            model_usage: Optional[dict[str, object]] = None,
            model_cost: Optional[dict[str, object]] = None,
    ) -> MessageModel:
        usage_data = usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        model_data = model or {"name": None, "provider": None}
        run_metadata = {
            "id": run_id,
            "status": "success",
        }
        assistant_metadata: dict[str, object] = {
            "model": model_data,
            "run": run_metadata,
            "usage": model_usage or usage_data,
        }
        if model_cost:
            assistant_metadata["cost"] = model_cost

        with get_session() as db_session:
            if user_message_id:
                user_msg = db_session.get(MessageModel, user_message_id)
                if user_msg:
                    user_meta = dict(user_msg.metadata_ or {})
                    user_meta["run"] = run_metadata
                    user_msg.metadata_ = user_meta
                    db_session.add(user_msg)

            assistant_msg = MessageModel(
                session_id=session_id,
                role="assistant",
                content=content,
                type="text",
                token_estimate=token_estimate,
                parts=parts or [],
                metadata_=assistant_metadata,
            )
            db_session.add(assistant_msg)

            session_obj = db_session.get(SessionModel, session_id)
            if session_obj:
                session_obj.input_tokens += int(usage_data.get("input_tokens", 0))
                session_obj.output_tokens += int(usage_data.get("output_tokens", 0))
                session_obj.updated_at = datetime.now(timezone.utc)
                db_session.add(session_obj)

            db_session.commit()
            db_session.refresh(assistant_msg)
            return assistant_msg

    @staticmethod
    def record_agent_run_failure(
            *,
            user_message_id: Optional[str],
            session_id: str,
            run_id: str,
            error_message: str,
    ) -> MessageModel:
        run_metadata = {
            "id": run_id,
            "status": "failed",
            "error": error_message,
        }

        with get_session() as db_session:
            if user_message_id:
                user_msg = db_session.get(MessageModel, user_message_id)
                if user_msg:
                    user_meta = dict(user_msg.metadata_ or {})
                    user_meta["run"] = run_metadata
                    user_msg.metadata_ = user_meta
                    db_session.add(user_msg)

            failure_msg = MessageModel(
                session_id=session_id,
                role="assistant",
                content=f"Run failed: {error_message}",
                type="text",
                metadata_={"run": run_metadata},
            )
            db_session.add(failure_msg)

            session_obj = db_session.get(SessionModel, session_id)
            if session_obj:
                session_obj.updated_at = datetime.now(timezone.utc)
                db_session.add(session_obj)

            db_session.commit()
            db_session.refresh(failure_msg)
            return failure_msg

    @staticmethod
    def record_agent_run_canceled(
            *,
            session_id: str,
            run_id: str,
    ) -> bool:
        run_metadata = {
            "id": run_id,
            "status": "canceled",
        }

        with get_session() as db_session:
            user_msg = db_session.exec(
                select(MessageModel).where(
                    MessageModel.session_id == session_id,
                    MessageModel.role == "user",
                    func.json_extract(MessageModel.metadata_, "$.run.id") == run_id,
                )
            ).first()
            if not user_msg:
                return False

            user_meta = dict(user_msg.metadata_ or {})
            user_meta["run"] = run_metadata
            user_msg.metadata_ = user_meta
            db_session.add(user_msg)

            session_obj = db_session.get(SessionModel, session_id)
            if session_obj:
                session_obj.updated_at = datetime.now(timezone.utc)
                db_session.add(session_obj)

            db_session.commit()
            return True

    @classmethod
    def get_run_model_usage(cls, session_id: str, run_id: str) -> dict[str, object] | None:
        with get_session() as db_session:
            message = db_session.exec(
                select(MessageModel).where(
                    MessageModel.session_id == session_id,
                    MessageModel.role == "assistant",
                    func.json_extract(MessageModel.metadata_, "$.run.id") == run_id,
                )
            ).first()
            if not message:
                return None
            usage = (message.metadata_ or {}).get("usage")
            return dict(usage) if cls._is_model_usage_payload(usage) else None

    @classmethod
    def get_session_model_usage(cls, session_id: str) -> dict[str, object]:
        aggregate = cls._empty_model_usage_payload()
        with get_session() as db_session:
            messages = db_session.exec(
                select(MessageModel).where(
                    MessageModel.session_id == session_id,
                    MessageModel.role == "assistant",
                )
            ).all()
            for message in messages:
                usage = (message.metadata_ or {}).get("usage")
                if cls._is_model_usage_payload(usage):
                    cls._merge_model_usage(aggregate, usage)
        return {
            "session_id": session_id,
            "model_usage": aggregate,
        }

    @staticmethod
    def update_session_usage(session_id: str, input_tokens: int, output_tokens: int) -> None:
        with get_session() as db_session:
            session_obj = db_session.get(SessionModel, session_id)
            if not session_obj:
                return
            session_obj.input_tokens += input_tokens
            session_obj.output_tokens += output_tokens
            session_obj.updated_at = datetime.now(timezone.utc)
            db_session.add(session_obj)
            db_session.commit()
            logger.debug(
                f"Updated usage for session {session_id}: +{input_tokens} in, +{output_tokens} out"
            )

    @staticmethod
    def append_memory_compaction_message(
            *,
            session_id: str,
            content: str,
            usage: dict[str, int],
            from_created_at: datetime,
            cutoff_created_at: datetime,
            message_count: int,
            token_estimate: int = 0,
            db_session: DBSession | None = None,
    ) -> MessageModel:
        usage_data = {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(
                usage.get("total_tokens")
                or int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            ),
        }
        message = MessageModel(
            session_id=session_id,
            role="memory",
            type="compaction",
            content=content,
            token_estimate=max(0, int(token_estimate)),
            metadata_={
                "usage": usage_data,
                "compaction": {
                    "from_created_at": _utc_text(from_created_at),
                    "cutoff_created_at": _utc_text(cutoff_created_at),
                    "message_count": max(0, int(message_count)),
                },
            },
        )

        if db_session is not None:
            db_session.add(message)
            return message

        with get_session() as owned_session:
            owned_session.add(message)
            owned_session.commit()
            owned_session.refresh(message)
            return message

    def get_session_insights(
            self,
            session_id: str,
            *,
            range_key: str = "last_7_days",
            timezone_name: str = "UTC",
    ) -> dict[str, object]:
        with get_session() as db_session:
            session_obj = db_session.get(SessionModel, session_id)
            if not session_obj:
                return {
                    "session_id": session_id,
                    "range": self._build_usage_range(range_key, timezone_name),
                    "usage": self._empty_usage_payload(),
                    "model_usage": self._empty_model_usage_payload(),
                    "memory": None,
                }

            usage_range = self._build_usage_range(range_key, timezone_name)
            messages = list(
                db_session.exec(
                    select(MessageModel)
                    .where(MessageModel.session_id == session_id)
                    .order_by(MessageModel.created_at)  # type: ignore[arg-type]
                ).all()
            )

            range_start = _utc_datetime(datetime.fromisoformat(str(usage_range["start_utc"]).replace("Z", "+00:00")))
            range_end = _utc_datetime(datetime.fromisoformat(str(usage_range["end_utc"]).replace("Z", "+00:00")))
            buckets = self._build_daily_buckets(usage_range)
            archived_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            range_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            model_usage_totals = self._empty_model_usage_payload()

            for message in messages:
                usage_payload = (message.metadata_ or {}).get("usage")
                if message.role == "assistant" and self._is_model_usage_payload(usage_payload):
                    self._merge_model_usage(model_usage_totals, usage_payload)

                if not self._is_usage_message(message):
                    continue
                usage = self._extract_usage(message.metadata_)
                if not usage:
                    continue

                archived_totals["input_tokens"] += usage["input_tokens"]
                archived_totals["output_tokens"] += usage["output_tokens"]
                archived_totals["total_tokens"] += usage["total_tokens"]

                created_at = _utc_datetime(message.created_at)
                if not (range_start <= created_at < range_end):
                    continue

                local_day = created_at.astimezone(ZoneInfo(str(usage_range["timezone"]))).date().isoformat()
                bucket = buckets.get(local_day)
                if not bucket:
                    continue

                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    bucket[key] += usage[key]
                    range_totals[key] += usage[key]

            session_totals = {
                "input_tokens": int(session_obj.input_tokens),
                "output_tokens": int(session_obj.output_tokens),
                "total_tokens": int(session_obj.input_tokens + session_obj.output_tokens),
            }
            unattributed = {
                "input_tokens": max(0, session_totals["input_tokens"] - archived_totals["input_tokens"]),
                "output_tokens": max(0, session_totals["output_tokens"] - archived_totals["output_tokens"]),
                "total_tokens": max(0, session_totals["total_tokens"] - archived_totals["total_tokens"]),
            }

            memory = self._build_memory_payload(session_obj.memory)

            return {
                "session_id": session_id,
                "range": usage_range,
                "usage": {
                    "daily": list(buckets.values()),
                    "range_totals": range_totals,
                    "session_totals": session_totals,
                    "archived_totals": archived_totals,
                    "unattributed_system_usage": unattributed,
                },
                "model_usage": model_usage_totals,
                "memory": memory,
            }

    def load_chat_messages(
            self,
            session_id: str,
            *,
            cutoff_created_at: Optional[datetime] = None,
            db_session: DBSession | None = None,
    ) -> list[MessageModel]:
        """Load chat messages after the compaction cutoff.

        `cutoff_created_at` is the end of the already-compacted history, so it
        is an exclusive lower bound for messages that still need live context.
        """
        if db_session is not None:
            return self._load_chat_messages(db_session, session_id, cutoff_created_at)

        with get_session() as owned_session:
            return self._load_chat_messages(owned_session, session_id, cutoff_created_at)

    @classmethod
    def _load_chat_messages(
            cls,
            db_session: DBSession,
            session_id: str,
            cutoff_created_at: Optional[datetime],
    ) -> list[MessageModel]:
        filters = [
            MessageModel.session_id == session_id,
            MessageModel.role.in_(("user", "assistant")),  # type:ignore
        ]
        if cutoff_created_at is not None:
            compacted_until_created_at = _utc_datetime(cutoff_created_at)
            filters.append(MessageModel.created_at > compacted_until_created_at)  # type: ignore[arg-type]

        statement = (
            select(MessageModel)
            .where(*filters)
            .order_by(MessageModel.created_at)  # type: ignore[arg-type]
        )
        return list(db_session.exec(statement).all())

    @classmethod
    def _build_usage_range(cls, range_key: str, timezone_name: str) -> dict[str, object]:
        tz = cls._load_timezone(timezone_name)
        now_local = datetime.now(tz)
        today = now_local.date()
        normalized_range = range_key if range_key in {
            "today",
            "yesterday",
            "last_7_days",
            "last_30_days",
            "last_90_days",
        } else "last_7_days"

        if normalized_range == "today":
            start_day = today
            end_local = now_local
            end_day = today
        elif normalized_range == "yesterday":
            start_day = today - timedelta(days=1)
            end_local = datetime.combine(today, time.min, tzinfo=tz)
            end_day = start_day
        else:
            day_count = {
                "last_7_days": 7,
                "last_30_days": 30,
                "last_90_days": 90,
            }[normalized_range]
            start_day = today - timedelta(days=day_count - 1)
            end_local = now_local
            end_day = today

        start_local = datetime.combine(start_day, time.min, tzinfo=tz)
        return {
            "key": normalized_range,
            "timezone": tz.key,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "start_utc": _utc_text(start_local),
            "end_utc": _utc_text(end_local),
        }

    @staticmethod
    def _load_timezone(timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name or "UTC")
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @classmethod
    def _build_daily_buckets(cls, usage_range: dict[str, object]) -> dict[str, dict[str, object]]:
        tz = cls._load_timezone(str(usage_range["timezone"]))
        start_day = date.fromisoformat(str(usage_range["start_date"]))
        end_day = date.fromisoformat(str(usage_range["end_date"]))
        buckets: dict[str, dict[str, object]] = {}
        current_day = start_day
        while current_day <= end_day:
            day_start = datetime.combine(current_day, time.min, tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            day_key = current_day.isoformat()
            buckets[day_key] = {
                "date": day_key,
                "period_start_utc": _utc_text(day_start),
                "period_end_utc": _utc_text(day_end),
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
            current_day += timedelta(days=1)
        return buckets

    @staticmethod
    def _extract_usage(metadata: dict[str, object] | None) -> dict[str, int] | None:
        usage = (metadata or {}).get("usage")
        if not isinstance(usage, dict):
            return None

        request = usage.get("request")
        if isinstance(request, dict):
            request_total = request.get("total")
            if isinstance(request_total, dict):
                input_tokens = int(request_total.get("input_tokens") or 0)
                output_tokens = int(request_total.get("output_tokens") or 0)
                total_tokens = int(request_total.get("total_tokens") or input_tokens + output_tokens)
                return {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                }

        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _is_usage_message(message: MessageModel) -> bool:
        return message.role == "assistant" or (message.role == "memory" and message.type == "compaction")

    @classmethod
    def _build_memory_payload(cls, memory: object) -> dict[str, object] | None:
        if not isinstance(memory, dict):
            return None

        payload = dict(memory)
        compaction = payload.get("compaction")
        if isinstance(compaction, dict):
            next_compaction = dict(compaction)
            summary = next_compaction.get("summary")
            next_compaction["summary_token_estimate"] = cls._estimate_summary_tokens(
                summary if isinstance(summary, str) else "")
            payload["compaction"] = next_compaction
        return payload

    @staticmethod
    def _estimate_summary_tokens(summary: str) -> int:
        if not summary:
            return 0
        return max(1, (len(summary) + 3) // 4)

    @staticmethod
    def _empty_usage_payload() -> dict[str, object]:
        empty_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return {
            "daily": [],
            "range_totals": dict(empty_totals),
            "session_totals": dict(empty_totals),
            "archived_totals": dict(empty_totals),
            "unattributed_system_usage": dict(empty_totals),
        }

    @staticmethod
    def _empty_model_usage_payload() -> dict[str, object]:
        return {
            "version": 1,
            "request": {
                "total": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "by_model": {},
            },
            "classifier": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "request_count": 0,
                "models": [],
            },
        }

    @staticmethod
    def _is_model_usage_payload(value: object) -> bool:
        return isinstance(value, dict) and isinstance(value.get("request"), dict)

    @classmethod
    def _merge_model_usage(cls, aggregate: dict[str, object], model_usage: dict[str, object]) -> None:
        request = model_usage.get("request")
        if isinstance(request, dict):
            request_total = request.get("total")
            if isinstance(request_total, dict):
                cls._merge_token_counts(aggregate["request"]["total"], request_total)  # type: ignore[index]

            by_model = request.get("by_model")
            if isinstance(by_model, dict):
                aggregate_by_model = aggregate["request"]["by_model"]  # type: ignore[index]
                for model_id, usage in by_model.items():
                    if not isinstance(model_id, str) or not isinstance(usage, dict):
                        continue
                    target = aggregate_by_model.setdefault(  # type: ignore[attr-defined]
                        model_id,
                        {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "request_count": 0},
                    )
                    cls._merge_token_counts(target, usage)
                    target["request_count"] += int(usage.get("request_count") or 0)

        classifier = model_usage.get("classifier")
        if isinstance(classifier, dict):
            aggregate_classifier = aggregate["classifier"]  # type: ignore[index]
            cls._merge_token_counts(aggregate_classifier, classifier)
            aggregate_classifier["request_count"] += int(classifier.get("request_count") or 0)
            models = aggregate_classifier["models"]
            model = classifier.get("model")
            if isinstance(model, str) and model and model not in models:
                models.append(model)
            extra_models = classifier.get("models")
            if isinstance(extra_models, list):
                for extra_model in extra_models:
                    if isinstance(extra_model, str) and extra_model and extra_model not in models:
                        models.append(extra_model)
            models.sort()

    @staticmethod
    def _merge_token_counts(target: dict[str, int], usage: dict[str, object]) -> None:
        target["input_tokens"] += int(usage.get("input_tokens") or 0)
        target["output_tokens"] += int(usage.get("output_tokens") or 0)
        target["total_tokens"] += int(
            usage.get("total_tokens")
            or int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        )
