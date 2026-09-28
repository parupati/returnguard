import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from databricks.sdk.service.sql import StatementState

from conftest import make_decision
from returnguard.enums import InterventionType
from returnguard.lakehouse import (
    DecisionLogEntry,
    LakehouseError,
    LakehouseStore,
    WarehouseExecutor,
)


class FakeExecutor:
    def __init__(self, *responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params):
        self.calls.append((sql, dict(params)))
        return self.responses.pop(0) if self.responses else []


def _store(*responses):
    executor = FakeExecutor(*responses)
    return LakehouseStore(executor, "databricks-hackathon", "frontier"), executor


PROFILE_ROW = {
    "customer_id": "CUST-0023",
    "email": "ava@example.com",
    "loyalty_tier": "gold",
    "preferred_channel": "web",
    "marketing_opt_in": "true",
    "lifetime_value": "16057.93",
    "churn_probability": "0.016561",
    "lifetime_orders": "30",
    "refunded_orders": "2",
    "historical_return_rate": "0.0667",
    "support_cases_30d": "0",
}


def test_customer_by_email_maps_row_and_uses_parameters():
    store, executor = _store([PROFILE_ROW])
    record = store.customer_by_email("AVA@example.com")

    sql, params = executor.calls[0]
    assert "`databricks-hackathon`.`frontier`.customer_return_profile" in sql
    assert params == {"email": "AVA@example.com"}
    assert record.email == "ava@example.com"
    assert record.profile.customer_id == "CUST-0023"
    assert record.profile.marketing_opt_in is True
    assert record.profile.lifetime_value == pytest.approx(16057.93)
    assert record.profile.churn_risk == pytest.approx(0.016561)


def test_customer_by_email_handles_missing_customer_and_null_churn():
    store, _ = _store([])
    assert store.customer_by_email("nobody@example.com") is None

    store, _ = _store([{**PROFILE_ROW, "churn_probability": None, "marketing_opt_in": "false"}])
    profile = store.customer_by_email("ava@example.com").profile
    assert profile.churn_risk is None
    assert profile.marketing_opt_in is False


def test_product_stats_passes_ids_as_json_array():
    store, executor = _store([{"product_id": "PROD-004", "category": "Beauty", "return_rate": "0.0877"}])
    stats = store.product_stats(["PROD-004", "PROD-999"])

    assert stats["PROD-004"].category == "Beauty"
    assert stats["PROD-004"].return_rate == pytest.approx(0.0877)
    assert "PROD-999" not in stats
    assert json.loads(executor.calls[0][1]["ids"]) == ["PROD-004", "PROD-999"]


def test_empty_id_lists_skip_the_query():
    store, executor = _store()
    assert store.product_stats([]) == {}
    assert store.decided_order_ids([]) == frozenset()
    assert executor.calls == []


def test_prior_interventions_maps_outcomes():
    store, _ = _store(
        [
            {"order_id": "1001", "intervention_type": "usage_tips", "outcome": "returned"},
            {"order_id": "1002", "intervention_type": "none", "outcome": "kept"},
        ]
    )
    prior = store.prior_interventions("CUST-0023")
    assert prior[0].intervention_type is InterventionType.USAGE_TIPS
    assert prior[0].item_returned is True
    assert prior[1].item_returned is False


def test_decided_order_ids():
    store, _ = _store([{"order_id": "1001"}])
    assert store.decided_order_ids(["1001", "1002"]) == frozenset({"1001"})


def test_log_decision_writes_pending_row():
    store, executor = _store()
    incentive = {"incentive_type": "store_credit", "percent_of_item_price": 10, "justification": "gold tier"}
    entry = DecisionLogEntry(
        decision_id="d-1",
        decided_at=datetime(2026, 9, 28, 12, tzinfo=timezone.utc),
        customer_id="CUST-0023",
        customer_email="ava@example.com",
        order_id="1042",
        decision=make_decision(intervention_type="keep_incentive", incentive=incentive),
        policy_adjustments=("Capped incentive",),
    )
    store.log_decision(entry)

    sql, params = executor.calls[0]
    assert sql.startswith("INSERT INTO `databricks-hackathon`.`frontier`.intervention_log")
    assert "'pending'" in sql
    assert params["intervention_type"] == "keep_incentive"
    assert params["incentive_percent"] == "10.0"
    assert json.loads(params["policy_adjustments"]) == ["Capped incentive"]


def test_log_decision_without_incentive_sends_null():
    store, executor = _store()
    entry = DecisionLogEntry("d-2", datetime.now(timezone.utc), "C", "e@x.com", "1", make_decision(), ())
    store.log_decision(entry)
    assert executor.calls[0][1]["incentive_percent"] is None


def test_pending_decisions_and_record_outcome():
    store, executor = _store([{"decision_id": "d-1", "order_id": "1042", "customer_email": "ava@example.com"}])
    pending = store.pending_decisions()
    store.record_outcome("d-1", "returned")

    assert pending[0].order_id == "1042"
    sql, params = executor.calls[1]
    assert sql.startswith("UPDATE")
    assert params == {"outcome": "returned", "decision_id": "d-1"}


def _response(state, rows=None, columns=("a",), error=None):
    return SimpleNamespace(
        statement_id="s-1",
        status=SimpleNamespace(state=state, error=SimpleNamespace(message=error) if error else None),
        manifest=SimpleNamespace(schema=SimpleNamespace(columns=[SimpleNamespace(name=c) for c in columns])),
        result=SimpleNamespace(data_array=rows),
    )


class _FakeStatements:
    def __init__(self, first, *later):
        self.first = first
        self.later = list(later)
        self.execute_kwargs = {}

    def execute_statement(self, **kwargs):
        self.execute_kwargs = kwargs
        return self.first

    def get_statement(self, statement_id):
        return self.later.pop(0)


def test_warehouse_executor_polls_until_done_and_maps_rows():
    statements = _FakeStatements(
        _response(StatementState.PENDING),
        _response(StatementState.SUCCEEDED, rows=[["1", "x"]], columns=("id", "name")),
    )
    executor = WarehouseExecutor(SimpleNamespace(statement_execution=statements), "wh-1", poll_seconds=0)

    rows = executor.execute("SELECT :v", {"v": "1"})

    assert rows == [{"id": "1", "name": "x"}]
    assert statements.execute_kwargs["warehouse_id"] == "wh-1"
    assert statements.execute_kwargs["parameters"][0].name == "v"


def test_warehouse_executor_raises_on_failure():
    statements = _FakeStatements(_response(StatementState.FAILED, error="PERMISSION_DENIED"))
    executor = WarehouseExecutor(SimpleNamespace(statement_execution=statements), "wh-1", poll_seconds=0)
    with pytest.raises(LakehouseError, match="PERMISSION_DENIED"):
        executor.execute("SELECT 1", {})


def test_warehouse_executor_handles_empty_result():
    statements = _FakeStatements(_response(StatementState.SUCCEEDED, rows=None))
    executor = WarehouseExecutor(SimpleNamespace(statement_execution=statements), "wh-1", poll_seconds=0)
    assert executor.execute("SELECT 1", {}) == []
