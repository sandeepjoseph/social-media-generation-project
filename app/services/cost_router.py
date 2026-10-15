"""Small, opt-in routing policy for existing MoneyPrinter service calls.

This module only chooses among candidates explicitly supplied by the caller. It
does not discover credentials, call providers, or treat missing prices as free.
The default configuration leaves routing disabled and preserves the configured
provider/model pair.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_DIFFICULTY_TIER = {
    "routine": 1,
    "basic": 1,
    "moderate": 2,
    "complex": 3,
    "exceptional": 4,
}


def classify_task_difficulty(task_type: str, prompt: str) -> str:
    """Conservative local heuristic; routine formatting tasks stay at Tier 1."""
    task = str(task_type).lower()
    text = str(prompt or "").lower()
    if task in {"keyword_extraction", "social_metadata", "subtitle_formatting"}:
        return "routine"
    if task in {"scriptwriting", "continuity_correction", "translation"}:
        hard_constraints = (
            "multiple timelines",
            "multi-character",
            "character continuity",
            "multilingual",
            "alternate endings",
        )
        if len(text) > 5000 or any(marker in text for marker in hard_constraints):
            return "complex"
        if len(text) > 2500 or "additional user requirements" in text:
            return "moderate"
    return "routine"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    provider: str
    model: str
    tier: int
    reason: str
    estimated_cost: float | None
    cost_status: str
    cost_domain: str
    cache_key: str
    enabled: bool
    price_source: str = ""
    price_checked_on: str = ""
    billing_unit: str = ""


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def route_task(
    *,
    stage: str,
    task_type: str,
    difficulty: str = "routine",
    quality: str = "standard",
    current_provider: str = "",
    current_model: str = "",
    available_candidates: Sequence[Mapping[str, Any]] = (),
    config: Mapping[str, Any] | None = None,
    cost_domain: str = "api",
    exceptional_authorized: bool = False,
    request_fingerprint: str = "",
) -> RouteDecision:
    """Choose the cheapest explicitly priced candidate meeting task needs.

    Candidate mappings use ``provider``, ``model``, ``tier`` (0-4), optional
    ``estimated_cost`` (non-negative, in that provider's own cost domain), and
    optional ``max_difficulty`` / ``qualities`` capability constraints. Tier 4
    is never eligible without explicit per-call authorization.
    """
    cfg = config or {}
    enabled = bool(cfg.get("cost_router_enabled", False))
    cache_key = _fingerprint(
        {
            "stage": stage,
            "task_type": task_type,
            "difficulty": difficulty,
            "quality": quality,
            "provider": current_provider,
            "model": current_model,
            "request_fingerprint": request_fingerprint,
        }
    )
    requested_tier = _DIFFICULTY_TIER.get(str(difficulty).lower(), 2)
    baseline = RouteDecision(
        provider=current_provider,
        model=current_model,
        tier=requested_tier,
        reason="router disabled; preserve configured provider and model",
        estimated_cost=None,
        cost_status="unknown",
        cost_domain=cost_domain,
        cache_key=cache_key,
        enabled=enabled,
    )
    if not enabled:
        return baseline

    normalized_quality = str(quality).lower()
    candidates = []
    for index, item in enumerate(available_candidates):
        provider = str(item.get("provider", "")).strip()
        model = str(item.get("model", "")).strip()
        if not provider or not model:
            continue
        try:
            tier = int(item.get("tier", requested_tier))
        except (TypeError, ValueError):
            continue
        if not 0 <= tier <= 4 or tier < requested_tier:
            continue
        if tier == 4 and not exceptional_authorized:
            continue
        if tier == 3 and requested_tier < 3 and not any(
            bool(item.get(field))
            for field in ("lower_tier_failed", "economic_justification", "capability_bypass")
        ):
            continue
        maximum = _DIFFICULTY_TIER.get(
            str(item.get("max_difficulty", "exceptional")).lower(), 4
        )
        if maximum < requested_tier:
            continue
        qualities = item.get("qualities")
        if qualities and normalized_quality not in {
            str(value).lower() for value in qualities
        }:
            continue
        amount = item.get("estimated_cost")
        if isinstance(amount, bool):
            amount = None
        try:
            amount = None if amount is None else float(amount)
        except (TypeError, ValueError):
            amount = None
        if amount is not None and (amount < 0 or not math.isfinite(amount)):
            continue
        candidates.append(
            (
                amount,
                tier,
                provider,
                model,
                index,
                str(item.get("price_source", "") or ""),
                str(item.get("price_checked_on", "") or ""),
                str(item.get("billing_unit", "") or ""),
            )
        )

    known_cost = [candidate for candidate in candidates if candidate[0] is not None]
    if not known_cost:
        return RouteDecision(
            provider=baseline.provider,
            model=baseline.model,
            tier=baseline.tier,
            reason="no capable candidate has a known price; preserve configured provider and model",
            estimated_cost=None,
            cost_status="unknown",
            cost_domain=baseline.cost_domain,
            cache_key=baseline.cache_key,
            enabled=baseline.enabled,
        )

    selected = min(known_cost, key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
    amount, tier, provider, model, _, source, checked_on, billing_unit = selected
    return RouteDecision(
        provider=provider,
        model=model,
        tier=tier,
        reason=f"lowest known-cost capable candidate for {stage}/{task_type}",
        estimated_cost=amount,
        cost_status="known",
        cost_domain=cost_domain,
        cache_key=cache_key,
        enabled=True,
        price_source=source,
        price_checked_on=checked_on,
        billing_unit=billing_unit,
    )


class BudgetLedger:
    """Thread-safe, process-local budget guard with separate accounting domains."""

    def __init__(self, limits: Mapping[str, float] | None = None):
        self._limits = dict(limits or {})
        self._spent: dict[str, float] = {}
        self._lock = threading.Lock()

    def reserve(self, domain: str, amount: float | None) -> bool:
        """Reserve a known cost; unknown costs fail closed when a limit exists."""
        with self._lock:
            limit = self._limits.get(domain)
            if amount is None:
                return limit is None
            if amount < 0 or not math.isfinite(amount):
                return False
            current = self._spent.get(domain, 0.0)
            if limit is not None and current + amount > limit:
                return False
            self._spent[domain] = current + amount
            return True

    def spent(self, domain: str) -> float:
        with self._lock:
            return self._spent.get(domain, 0.0)


class ResponseCache:
    """Local SQLite cache for approved deterministic LLM request identities."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        with closing(sqlite3.connect(database_path, timeout=10)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS responses ("
                "cache_key TEXT PRIMARY KEY, response TEXT NOT NULL)"
            )
            connection.commit()

    def get(self, cache_key: str) -> str | None:
        with closing(sqlite3.connect(self.database_path, timeout=10)) as connection:
            row = connection.execute(
                "SELECT response FROM responses WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return row[0] if row else None

    def put(self, cache_key: str, response: str) -> None:
        with closing(sqlite3.connect(self.database_path, timeout=10)) as connection:
            connection.execute(
                "INSERT INTO responses (cache_key, response) VALUES (?, ?) "
                "ON CONFLICT(cache_key) DO NOTHING",
                (cache_key, response),
            )
            connection.commit()


class ExecutionGuard:
    """Per-process idempotency, retry ceiling, and bounded concurrency helper."""

    def __init__(self, *, max_attempts: int = 3, max_concurrency: int = 1):
        if max_attempts < 1 or max_concurrency < 1:
            raise ValueError("max_attempts and max_concurrency must be positive")
        self.max_attempts = max_attempts
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._completed: set[str] = set()
        self._lock = threading.Lock()

    def begin(self, idempotency_key: str, attempt: int) -> bool:
        if not idempotency_key or attempt < 1 or attempt > self.max_attempts:
            return False
        with self._lock:
            return idempotency_key not in self._completed

    def complete(self, idempotency_key: str) -> None:
        if idempotency_key:
            with self._lock:
                self._completed.add(idempotency_key)

    def acquire(self, blocking: bool = False) -> bool:
        return self._semaphore.acquire(blocking=blocking)

    def release(self) -> None:
        self._semaphore.release()


class DurableExecutionGuard:
    """SQLite-backed idempotency and budget reservations across restarts.

    Use a task-local or project-local database path. Each attempt is recorded
    before an external call, so a crash cannot silently replay an uncertain
    paid request. Unknown cost is rejected when a domain limit is configured.
    """

    def __init__(self, database_path: str, *, max_attempts: int = 3):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.database_path = database_path
        self.max_attempts = max_attempts
        with closing(self._connect()) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS executions ("
                "idempotency_key TEXT PRIMARY KEY, status TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS attempts ("
                "idempotency_key TEXT NOT NULL, attempt INTEGER NOT NULL, "
                "domain TEXT NOT NULL, amount REAL, job_id TEXT NOT NULL DEFAULT '', "
                "stage TEXT NOT NULL DEFAULT '', task_type TEXT NOT NULL DEFAULT '', "
                "provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', "
                "tier INTEGER, price_source TEXT NOT NULL DEFAULT '', "
                "price_checked_on TEXT NOT NULL DEFAULT '', billing_unit TEXT NOT NULL DEFAULT '', "
                "PRIMARY KEY (idempotency_key, attempt))"
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(attempts)")
            }
            if "job_id" not in columns:
                connection.execute(
                    "ALTER TABLE attempts ADD COLUMN job_id TEXT NOT NULL DEFAULT ''"
                )
            for name, definition in (
                ("stage", "TEXT NOT NULL DEFAULT ''"),
                ("task_type", "TEXT NOT NULL DEFAULT ''"),
                ("provider", "TEXT NOT NULL DEFAULT ''"),
                ("model", "TEXT NOT NULL DEFAULT ''"),
                ("tier", "INTEGER"),
                ("price_source", "TEXT NOT NULL DEFAULT ''"),
                ("price_checked_on", "TEXT NOT NULL DEFAULT ''"),
                ("billing_unit", "TEXT NOT NULL DEFAULT ''"),
                ("input_chars", "INTEGER"),
                ("output_chars", "INTEGER"),
                ("actual_cost", "REAL"),
                ("actual_usage_source", "TEXT NOT NULL DEFAULT 'unknown'"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE attempts ADD COLUMN {name} {definition}"
                    )

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def reserve(
        self,
        idempotency_key: str,
        attempt: int,
        domain: str,
        amount: float | None,
        limits: Mapping[str, float] | None = None,
        job_id: str = "",
        trace: Mapping[str, Any] | None = None,
    ) -> bool:
        """Atomically reserve an attempt and reject duplicates or budget overruns."""
        if not idempotency_key or not domain or not 1 <= attempt <= self.max_attempts:
            return False
        if amount is not None and (amount < 0 or not math.isfinite(amount)):
            return False
        limits = limits or {}
        limit = limits.get(domain)
        if amount is None and limit is not None:
            return False
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT status FROM executions WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    connection.rollback()
                    return False
                duplicate = connection.execute(
                    "SELECT 1 FROM attempts WHERE idempotency_key = ? AND attempt = ?",
                    (idempotency_key, attempt),
                ).fetchone()
                if duplicate:
                    connection.rollback()
                    return False
                scoped_limits = {domain: limit}
                if job_id:
                    scoped_limits[f"{domain}:video"] = limits.get(
                        f"{domain}:video"
                    )
                for scope, scope_limit in scoped_limits.items():
                    if scope_limit is None:
                        continue
                    if scope.endswith(":video"):
                        spent = connection.execute(
                            "SELECT COALESCE(SUM(amount), 0) FROM attempts "
                            "WHERE domain = ? AND job_id = ?",
                            (domain, job_id),
                        ).fetchone()[0]
                    else:
                        spent = connection.execute(
                            "SELECT COALESCE(SUM(amount), 0) FROM attempts WHERE domain = ?",
                            (domain,),
                        ).fetchone()[0]
                    if amount is None or spent + amount > scope_limit:
                        connection.rollback()
                        return False
                connection.execute(
                    "INSERT INTO attempts (idempotency_key, attempt, domain, amount, job_id, "
                    "stage, task_type, provider, model, tier, price_source, price_checked_on, "
                    "billing_unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ",
                    (
                        idempotency_key,
                        attempt,
                        domain,
                        amount,
                        job_id,
                        str((trace or {}).get("stage", "")),
                        str((trace or {}).get("task_type", "")),
                        str((trace or {}).get("provider", "")),
                        str((trace or {}).get("model", "")),
                        (trace or {}).get("tier"),
                        str((trace or {}).get("price_source", "")),
                        str((trace or {}).get("price_checked_on", "")),
                        str((trace or {}).get("billing_unit", "")),
                    ),
                )
                connection.execute(
                    "INSERT INTO executions (idempotency_key, status) VALUES (?, 'running') "
                    "ON CONFLICT(idempotency_key) DO UPDATE SET status = 'running'",
                    (idempotency_key,),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def complete(
        self,
        idempotency_key: str,
        *,
        attempt: int | None = None,
        input_chars: int | None = None,
        output_chars: int | None = None,
        actual_cost: float | None = None,
        actual_usage_source: str = "unknown",
    ) -> bool:
        """Finalize once and attach observed text lengths/provider-reported usage."""
        with closing(self._connect()) as connection:
            if attempt is not None:
                connection.execute(
                    "UPDATE attempts SET input_chars = ?, output_chars = ?, actual_cost = ?, "
                    "actual_usage_source = ? WHERE idempotency_key = ? AND attempt = ?",
                    (
                        input_chars,
                        output_chars,
                        actual_cost,
                        actual_usage_source,
                        idempotency_key,
                        attempt,
                    ),
                )
            cursor = connection.execute(
                "UPDATE executions SET status = 'completed' "
                "WHERE idempotency_key = ? AND status != 'completed'",
                (idempotency_key,),
            )
            return cursor.rowcount == 1

    def mark_uncertain(self, idempotency_key: str) -> bool:
        """Hold a request that may have reached a paid provider; never auto-replay."""
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE executions SET status = 'uncertain' "
                "WHERE idempotency_key = ? AND status = 'running'",
                (idempotency_key,),
            )
            return cursor.rowcount == 1

    def spent(self, domain: str) -> float:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM attempts WHERE domain = ?",
                (domain,),
            ).fetchone()
        return float(row[0])

    def metrics(self, domain: str | None = None) -> dict[str, int | float]:
        """Return persisted attempts and estimated costs, separated by domain."""
        with closing(self._connect()) as connection:
            where = " WHERE domain = ?" if domain else ""
            values = (domain,) if domain else ()
            attempts, estimated, unknown, input_chars, output_chars, actual_cost, actual_unknown = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount), 0), "
                "COALESCE(SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END), 0), "
                "COALESCE(SUM(input_chars), 0), COALESCE(SUM(output_chars), 0), "
                "COALESCE(SUM(actual_cost), 0), "
                "COALESCE(SUM(CASE WHEN actual_usage_source = 'unknown' THEN 1 ELSE 0 END), 0) "
                f"FROM attempts{where}",
                values,
            ).fetchone()
            completed = connection.execute(
                "SELECT COUNT(*) FROM executions WHERE status = 'completed'"
            ).fetchone()[0]
        return {
            "attempts": int(attempts),
            "estimated_cost": float(estimated),
            "unknown_cost_attempts": int(unknown),
            "completed_requests": int(completed),
            "observed_input_chars": int(input_chars),
            "observed_output_chars": int(output_chars),
            "provider_reported_actual_cost": float(actual_cost),
            "provider_usage_unknown_attempts": int(actual_unknown),
        }
