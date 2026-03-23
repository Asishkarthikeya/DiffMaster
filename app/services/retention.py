"""
FR-4: Data Retention Policy Enforcement

Provides scheduled cleanup for:
- Audit logs (JSONL entries older than retention_days)
- Cache files (embeddings, tmp files older than cache_retention_days)

Intended to be called by a Celery beat task or cron job.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("diffmaster.retention")


class RetentionPolicy:
    """
    Manages data retention across DiffMaster storage systems.

    Retention targets:
    - Audit logs: configurable (default 90 days)
    - Cache files: configurable (default 30 days)

    Usage:
        policy = RetentionPolicy()
        results = policy.run_all()
        # results = {"audit_logs": {"purged": 12, "status": "ok"}, "cache_files": {...}}
    """

    def __init__(
        self,
        audit_retention_days: Optional[int] = None,
        cache_retention_days: Optional[int] = None,
    ):
        from app.core.config import settings

        self.audit_retention_days = audit_retention_days or settings.AUDIT_LOG_RETENTION_DAYS
        self.cache_retention_days = cache_retention_days or settings.CACHE_RETENTION_DAYS

    def run_all(self) -> dict:
        """
        Execute all retention policies.

        Returns:
            Summary dict with results per storage type.
        """
        from app.services.audit import get_audit_logger

        results: dict = {}
        audit = get_audit_logger()

        # 1. Audit log retention
        try:
            purged = audit.enforce_retention()
            results["audit_logs"] = {"purged": purged, "status": "ok"}
        except Exception as e:
            logger.error(f"Audit log retention failed: {e}")
            results["audit_logs"] = {"status": "error", "error": str(e)}

        # 2. Cache file retention
        try:
            purged_files = self._purge_cache_files()
            results["cache_files"] = {"purged": purged_files, "status": "ok"}
        except Exception as e:
            logger.error(f"Cache file retention failed: {e}")
            results["cache_files"] = {"status": "error", "error": str(e)}

        logger.info(f"Retention policy completed: {results}")
        audit.log_event("retention_policy_run", results)
        return results

    def _purge_cache_files(self) -> int:
        """
        Remove stale cache files older than cache_retention_days.

        Searches common DiffMaster cache locations:
        - ./cache/
        - /tmp/diffmaster/
        - $DIFFMASTER_CACHE_DIR (if set)

        Returns:
            Number of files deleted.
        """
        from app.core.config import settings

        cache_dirs = [
            Path("./cache"),
            Path("/tmp/diffmaster"),
            Path(os.getenv("DIFFMASTER_CACHE_DIR", "./cache")),
        ]

        cutoff_ts = time.time() - (self.cache_retention_days * 86400)
        purged = 0

        for cache_dir in set(cache_dirs):  # dedup paths
            if not cache_dir.exists():
                continue
            for f in cache_dir.rglob("*"):
                if f.is_file():
                    try:
                        if f.stat().st_mtime < cutoff_ts:
                            f.unlink()
                            purged += 1
                            logger.debug(f"Purged cache file: {f}")
                    except OSError as e:
                        logger.warning(f"Could not delete {f}: {e}")

        return purged


def get_retention_policy() -> RetentionPolicy:
    """Return a configured RetentionPolicy instance."""
    return RetentionPolicy()
