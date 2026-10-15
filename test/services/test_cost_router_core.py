from app.services.cost_router import (
    BudgetLedger,
    DurableExecutionGuard,
    ExecutionGuard,
    ResponseCache,
    classify_task_difficulty,
    route_task,
)
from app.services.cost_router_overrides import apply_new_job_overrides
from app.services.flow_cost_router import FlowCandidate, recommend_shot


def test_disabled_router_preserves_configured_provider_and_model():
    decision = route_task(
        stage="script",
        task_type="scriptwriting",
        current_provider="configured-provider",
        current_model="configured-model",
        available_candidates=[
            {"provider": "candidate", "model": "m1", "tier": 1, "estimated_cost": 0}
        ],
    )

    assert (decision.provider, decision.model) == (
        "configured-provider",
        "configured-model",
    )
    assert decision.cost_status == "unknown"


def test_local_classifier_keeps_routine_work_at_lowest_tier():
    assert classify_task_difficulty("keyword_extraction", "x" * 8000) == "routine"
    assert classify_task_difficulty("scriptwriting", "Write a short outline") == "routine"
    assert (
        classify_task_difficulty(
            "scriptwriting", "Use multiple timelines and maintain character continuity"
        )
        == "complex"
    )


def test_enabled_router_chooses_lowest_known_capable_candidate():
    decision = route_task(
        stage="script",
        task_type="scriptwriting",
        current_provider="configured-provider",
        current_model="configured-model",
        config={"cost_router_enabled": True},
        available_candidates=[
            {"provider": "higher-cost", "model": "m1", "tier": 1, "estimated_cost": 3},
            {"provider": "lower-cost", "model": "m2", "tier": 1, "estimated_cost": 0.2},
            {"provider": "unpriced", "model": "m3", "tier": 1},
        ],
    )

    assert (decision.provider, decision.model, decision.estimated_cost) == (
        "lower-cost",
        "m2",
        0.2,
    )
    assert decision.cost_status == "known"


def test_unknown_cost_is_not_free_and_exceptional_tier_requires_authorization():
    decision = route_task(
        stage="review",
        task_type="quality_review",
        difficulty="exceptional",
        current_provider="configured-provider",
        current_model="configured-model",
        config={"cost_router_enabled": True},
        available_candidates=[
            {"provider": "unknown", "model": "m1", "tier": 4},
            {"provider": "priced", "model": "m2", "tier": 4, "estimated_cost": 0},
        ],
    )

    assert (decision.provider, decision.model) == (
        "configured-provider",
        "configured-model",
    )
    assert decision.estimated_cost is None
    assert decision.cost_status == "unknown"


def test_budget_ledger_separates_domains_and_rejects_overage():
    ledger = BudgetLedger({"text": 1.0, "speech": 0.25})

    assert ledger.reserve("text", 0.75)
    assert not ledger.reserve("text", 0.3)
    assert ledger.reserve("speech", 0.25)
    assert not ledger.reserve("speech", None)
    assert ledger.spent("text") == 0.75


def test_response_cache_stores_a_response_once(tmp_path):
    cache = ResponseCache(str(tmp_path / "responses.sqlite3"))

    assert cache.get("request-a") is None
    cache.put("request-a", "cached result")
    cache.put("request-a", "later result")

    assert cache.get("request-a") == "cached result"


def test_execution_guard_limits_attempts_and_prevents_completed_replay():
    guard = ExecutionGuard(max_attempts=2, max_concurrency=1)

    assert guard.begin("request-a", 1)
    assert guard.begin("request-a", 2)
    assert not guard.begin("request-a", 3)
    guard.complete("request-a")
    assert not guard.begin("request-a", 1)
    assert guard.acquire()
    assert not guard.acquire()
    guard.release()


def test_durable_guard_reserves_once_and_persists_budget(tmp_path):
    database = str(tmp_path / "ledger.sqlite3")
    guard = DurableExecutionGuard(database, max_attempts=2)

    assert guard.reserve("job-a", 1, "video_units", 10, {"video_units": 15})
    assert not guard.reserve("job-a", 1, "video_units", 10, {"video_units": 15})
    assert guard.mark_uncertain("job-a")
    assert not guard.reserve("job-a", 2, "video_units", 1, {"video_units": 15})
    assert not guard.reserve("job-b", 1, "video_units", 6, {"video_units": 15})

    restarted = DurableExecutionGuard(database, max_attempts=2)
    assert restarted.spent("video_units") == 10
    assert restarted.reserve("job-c", 1, "video_units", 5, {"video_units": 15})
    assert restarted.complete("job-c", attempt=1, input_chars=12, output_chars=34)
    assert restarted.metrics("video_units")["completed_requests"] == 1


def test_override_loader_allows_known_settings_and_ignores_other_fields(tmp_path):
    override_file = tmp_path / "router-overrides.json"
    base = {"llm_provider": "configured-provider", "provider_credential": "stub"}
    override_file.write_text(
        '{"enabled":true,"cache_enabled":true,"unrecognized":"ignore",'
        '"provider_credential":"ignore", "candidates":[{"provider":"p",'
        '"model":"m","estimated_cost":0.2,"unrecognized":"ignore"}]}',
        encoding="utf-8",
    )

    snapshot = apply_new_job_overrides(base, override_file)

    assert snapshot["cost_router_enabled"] is True
    assert snapshot["cost_router_cache_enabled"] is True
    assert snapshot["llm_provider"] == "configured-provider"
    assert snapshot["provider_credential"] == "stub"
    assert snapshot["cost_router_candidates"] == [
        {"provider": "p", "model": "m", "estimated_cost": 0.2}
    ]


def test_flow_recommendation_requires_fresh_confirmed_plan_compatible_quote():
    candidates = [
        FlowCandidate(
            model="Sample Model A",
            duration_seconds=8,
            resolution="720p",
            credits=10,
            plan_eligibility=("Standard", "Premium"),
            capabilities=frozenset({"references", "extension"}),
            quote_date="2026-10-01",
            source="test fixture",
            ui_confirmed=True,
        ),
        FlowCandidate(
            model="Sample Model B",
            duration_seconds=8,
            resolution="720p",
            credits=5,
            plan_eligibility=("Premium",),
            capabilities=frozenset({"references", "extension"}),
            quote_date="2026-10-01",
            source="test fixture",
            ui_confirmed=False,
        ),
    ]
    recommendation = recommend_shot(
        prompt="sample shot",
        duration_seconds=8,
        resolution="720p",
        required_capabilities={"extension"},
        subscription_plan="Standard",
        candidates=candidates,
        today="2026-10-15",
    )

    assert recommendation.model == "Sample Model A"
    assert recommendation.credits == 10
    assert recommendation.manual_action_required


def test_flow_recommendation_holds_for_stale_quote_or_provider_check():
    candidate = FlowCandidate(
        model="Sample Model",
        duration_seconds=8,
        resolution="720p",
        credits=5,
        plan_eligibility=("Standard",),
        quote_date="2026-01-01",
        source="test fixture",
        ui_confirmed=True,
    )
    stale = recommend_shot(
        prompt="sample shot",
        duration_seconds=8,
        resolution="720p",
        subscription_plan="Standard",
        candidates=[candidate],
        today="2026-10-15",
    )
    blocked = recommend_shot(
        prompt="sample shot",
        duration_seconds=8,
        resolution="720p",
        subscription_plan="Standard",
        candidates=[candidate],
        today="2026-10-15",
        provider_account_check_required=True,
    )

    assert stale.model is None
    assert stale.credits is None
    assert blocked.model is None
    assert blocked.credits is None
