"""
FR-4: Enterprise Audit Logging

Writes structured JSONL audit logs with configurable retention.
Each entry: { "ts", "event", "actor", "data" }

Supports:
- Per-event structured data
- Configurable log path
- Automatic retention enforcement (delete entries older than N days)
- Query/filter for compliance reporting
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("diffmaster.audit")


class AuditLogger:
    """
    Structured JSONL audit logger with configurable data retention.

    Usage:
        audit = get_audit_logger()
        audit.log_event("review_completed", {"repo": "org/repo", "pr": 42, "comments": 5})
        audit.enforce_retention()  # run periodically to purge old entries
    """

    def __init__(self, log_path: str = None, retention_days: int = None, enabled: bool = None):
        from app.core.config import settings

        self.retention_days = retention_days if retention_days is not None else settings.AUDIT_LOG_RETENTION_DAYS
        self.enabled = enabled if enabled is not None else settings.ENABLE_AUDIT_LOG
        self._service_account = settings.SERVICE_ACCOUNT_ID
        self.log_path = Path(log_path or settings.AUDIT_LOG_PATH)
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Create log directory if it doesn't exist."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Fall back to local ./logs/ directory
            self.log_path = Path("./logs/audit.jsonl")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        event: str,
        data: Optional[dict[str, Any]] = None,
        actor: Optional[str] = None,
    ) -> None:
        """
        Write a structured audit log entry.

        Args:
            event: Event type (e.g. "review_started", "webhook_rejected")
            data: Arbitrary event metadata dict
            actor: Identity performing the action (defaults to service account ID)
        """
        if not self.enabled:
            return

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "actor": actor or self._service_account or "diffmaster",
            "data": data or {},
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Audit log write failed: {e}")

        logger.info(f"[AUDIT] {event} | {json.dumps(data or {})}")

    def enforce_retention(self) -> int:
        """
        Delete audit log entries older than retention_days.
        Rewrites the log file keeping only recent entries.

        Returns:
            Number of entries purged.
        """
        if not self.log_path.exists():
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept: list[str] = []
        purged = 0

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        entry_ts = datetime.fromisoformat(entry["ts"])
                        # Make offset-aware if naive
                        if entry_ts.tzinfo is None:
                            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
                        if entry_ts >= cutoff:
                            kept.append(line)
                        else:
                            purged += 1
                    except (json.JSONDecodeError, KeyError, ValueError):
                        kept.append(line)  # Preserve malformed entries

            with open(self.log_path, "w", encoding="utf-8") as f:
                for line in kept:
                    f.write(line + "\n")

            if purged > 0:
                self.log_event(
                    "retention_enforced",
                    {"purged_entries": purged, "retention_days": self.retention_days},
                )
                logger.info(f"Audit retention: purged {purged} entries older than {self.retention_days} days")
        except Exception as e:
            logger.error(f"Retention enforcement failed: {e}")

        return purged

    def query_events(
        self,
        event_type: Optional[str] = None,
        repo: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Query audit log entries with optional filters.

        Args:
            event_type: Filter by event name (e.g. "review_completed")
            repo: Filter by repo in data.repo field
            since: Only return entries after this datetime
            limit: Max entries to return

        Returns:
            List of matching audit log entries.
        """
        if not self.log_path.exists():
            return []

        results: list[dict] = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event_type and entry.get("event") != event_type:
                        continue
                    if repo and entry.get("data", {}).get("repo") != repo:
                        continue
                    if since:
                        entry_ts = datetime.fromisoformat(entry["ts"])
                        if entry_ts.tzinfo is None:
                            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
                        if entry_ts < since:
                            continue

                    results.append(entry)
                    if len(results) >= limit:
                        break
        except Exception as e:
            logger.error(f"Audit log query failed: {e}")

        return results

    def get_stats(self) -> dict:
        """Return summary statistics from the audit log."""
        if not self.log_path.exists():
            return {"total_entries": 0, "log_path": str(self.log_path)}

        counts: dict[str, int] = {}
        total = 0
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        event = entry.get("event", "unknown")
                        counts[event] = counts.get(event, 0) + 1
                        total += 1
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass

        return {
            "total_entries": total,
            "event_counts": counts,
            "log_path": str(self.log_path),
            "retention_days": self.retention_days,
        }


# Module-level singleton
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Return the module-level AuditLogger singleton."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
