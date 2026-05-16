"""
WebhookTrigger - Generic webhook handler with signature verification.
"""

import asyncio
import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

import shortuuid

logger = logging.getLogger(__name__)


@dataclass
class WebhookConfig:
    """Configuration for a webhook trigger."""
    secret: Optional[str] = None  # HMAC secret for signature verification
    event_filters: list[str] = field(default_factory=list)  # Only fire on these event types
    headers: dict[str, str] = field(default_factory=dict)  # Required headers
    debounce_ms: int = 1000  # Debounce window in ms


class WebhookTrigger:
    """
    Handles incoming webhook requests.

    Features:
    - HMAC-SHA256 signature verification (GitHub style)
    - Event type filtering
    - Required header validation
    - Debouncing to prevent trigger storms
    - Execution of instruction on match
    """

    def __init__(
        self,
        trigger_id: str,
        config: WebhookConfig,
        runtime,
        instruction: str,
    ) -> None:
        self.trigger_id = trigger_id
        self.config = config
        self.runtime = runtime
        self.instruction = instruction
        self._last_triggered_at: float = 0
        self._lock = asyncio.Lock()

    async def handle_request(
        self,
        headers: dict[str, str],
        body: bytes,
        raw_body: bytes,
    ) -> dict[str, object]:
        """
        Process an incoming webhook request.

        Args:
            headers: Request headers (lowercase keys)
            body: Parsed JSON body
            raw_body: Original raw bytes body

        Returns:
            Result dict with status, message, and trigger info
        """
        # 1. Debounce check
        if not self._check_debounce():
            return {
                "status": "debounced",
                "trigger_id": self.trigger_id,
                "message": "Trigger debounced due to rapid successive calls",
            }

        # 2. Verify signature if secret is configured
        if self.config.secret:
            if not self._verify_signature(headers, raw_body):
                logger.warning(f"Webhook {self.trigger_id}: signature verification failed")
                return {
                    "status": "unauthorized",
                    "trigger_id": self.trigger_id,
                    "message": "Signature verification failed",
                }

        # 3. Check event type filter
        event_type = headers.get("x-event-type") or headers.get("x-github-event") or "unknown"
        if self.config.event_filters and event_type not in self.config.event_filters:
            return {
                "status": "filtered",
                "trigger_id": self.trigger_id,
                "event_type": event_type,
                "message": f"Event type '{event_type}' not in filter list",
            }

        # 4. Check required headers
        for header_name, expected_value in self.config.headers.items():
            actual = headers.get(header_name.lower())
            if actual is None:
                return {
                    "status": "missing_header",
                    "trigger_id": self.trigger_id,
                    "header": header_name,
                    "message": f"Required header '{header_name}' is missing",
                }
            if expected_value and actual != expected_value:
                return {
                    "status": "header_mismatch",
                    "trigger_id": self.trigger_id,
                    "header": header_name,
                    "message": f"Header '{header_name}' value mismatch",
                }

        # 5. Execute the instruction
        await self._execute_instruction(event_type, body)

        return {
            "status": "triggered",
            "trigger_id": self.trigger_id,
            "event_type": event_type,
            "message": "Webhook trigger executed successfully",
        }

    def _check_debounce(self) -> bool:
        """Check if the request should be debounced."""
        import time
        now = time.monotonic() * 1000
        if now - self._last_triggered_at < self.config.debounce_ms:
            return False
        self._last_triggered_at = now
        return True

    def _verify_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """
        Verify HMAC-SHA256 signature (GitHub style).

        GitHub sends: X-Hub-Signature-256: sha256=<hex>
        """
        if not self.config.secret:
            return True

        signature = headers.get("x-hub-signature-256") or headers.get("x-hub-signature")
        if not signature:
            return False

        # Parse signature
        if signature.startswith("sha256="):
            expected_hex = signature[7:]
        elif signature.startswith("sha1="):
            # SHA1 fallback for older webhooks
            expected_hex = signature[5:]
            algo = "sha1"
        else:
            expected_hex = signature
            algo = "sha256"

        algo = "sha256" if "256" in signature[:10] else "sha1" if "sha1" in signature[:10] else "sha256"

        if algo == "sha256":
            mac = hmac.new(
                self.config.secret.encode(),
                raw_body,
                hashlib.sha256,
            )
        else:
            mac = hmac.new(
                self.config.secret.encode(),
                raw_body,
                hashlib.sha1,
            )

        expected = f"{algo}={mac.hexdigest()}"
        return hmac.compare_digest(expected, signature)

    async def _execute_instruction(self, event_type: str, body: bytes) -> None:
        """Execute the trigger's instruction via the runtime."""
        from datetime import datetime, timezone

        run_id = shortuuid.uuid()

        # Build context for the instruction
        context = {
            "trigger_id": self.trigger_id,
            "event_type": event_type,
            "body": body,
        }

        instruction_with_context = self.instruction
        try:
            import json
            body_json = json.loads(body) if isinstance(body, bytes) else body
            body_str = json.dumps(body_json, ensure_ascii=False, indent=2)
            instruction_with_context = (
                f"{self.instruction}\n\n"
                f"[Webhook Event Context]\n"
                f"Event Type: {event_type}\n"
                f"Trigger ID: {self.trigger_id}\n"
                f"Request Body:\n{body_str[:2000]}"
            )
        except Exception:
            pass

        logger.info(f"Webhook {self.trigger_id}: executing instruction (event={event_type})")

        try:
            # Run the instruction asynchronously
            asyncio.create_task(
                self._run_triggered_instruction(
                    instruction=instruction_with_context,
                    run_id=run_id,
                    trigger_id=self.trigger_id,
                )
            )
        except Exception as e:
            logger.error(f"Webhook {self.trigger_id}: failed to schedule instruction: {e}")

    async def _run_triggered_instruction(
        self,
        instruction: str,
        run_id: str,
        trigger_id: str,
    ) -> None:
        """Run the triggered instruction via run_registry."""
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc)
        finished_at = started_at
        result_status = "success"
        result_summary = None
        result_error = None

        try:
            runner_task = self.runtime.run_registry.start_run(
                session_id=trigger_id,
                instruction=instruction,
                run_id=run_id,
                source="webhook",
            )
            result = await runner_task
            finished_at = datetime.now(timezone.utc)

            if isinstance(result, dict):
                payload = result.get("payload", {})
                messages = payload.get("messages", []) if isinstance(payload, dict) else []
                last_message = messages[-1] if messages else {}
                content = str(last_message.get("content", ""))[:500]
                result_summary = content or None
        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            result_status = "failed"
            result_error = str(e)[:500]
            logger.exception(f"Webhook trigger {trigger_id} run failed")

        # Update trigger stats
        await self._update_trigger_stats(
            trigger_id=trigger_id,
            last_triggered_at=started_at,
            last_run_result={
                "status": result_status,
                "summary": result_summary,
                "error": result_error,
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
            },
        )

    @staticmethod
    async def _update_trigger_stats(
        trigger_id: str,
        last_triggered_at: datetime,
        last_run_result: dict,
    ) -> None:
        """Update trigger statistics in the database."""
        from app.core.db import get_session
        from app.models.database import TriggerModel

        try:
            with get_session() as session:
                trigger = session.get(TriggerModel, trigger_id)
                if trigger:
                    trigger.last_triggered_at = last_triggered_at
                    trigger.trigger_count = (trigger.trigger_count or 0) + 1
                    trigger.last_run_result = last_run_result
                    session.add(trigger)
                    session.commit()
        except Exception as e:
            logger.error(f"Failed to update trigger stats for {trigger_id}: {e}")
