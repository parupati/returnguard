"""Databricks Lakehouse access: return-risk features in, decisions and outcomes out (the learning loop)."""

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from returnguard.config import DatabricksSettings
from returnguard.context import CustomerProfile, PriorIntervention
from returnguard.decision import InterventionDecision
from returnguard.enums import InterventionType

Row = dict[str, str | None]
Outcome = Literal["kept", "returned"]


class LakehouseError(RuntimeError):
    pass


def workspace_client(settings: DatabricksSettings, env: Mapping[str, str] | None = None) -> WorkspaceClient:
    """Unattended identity when one exists (a Databricks job, or a service principal); browser login otherwise."""
    source = os.environ if env is None else env
    if source.get("DATABRICKS_RUNTIME_VERSION"):
        return WorkspaceClient()
    if source.get("DATABRICKS_CLIENT_ID") and source.get("DATABRICKS_CLIENT_SECRET"):
        return WorkspaceClient(host=settings.host)
    return WorkspaceClient(host=settings.host, auth_type="external-browser")


class SqlExecutor(Protocol):
    def execute(self, sql: str, params: Mapping[str, str | None]) -> list[Row]: ...


class WarehouseExecutor:
    def __init__(self, client: WorkspaceClient, warehouse_id: str, poll_seconds: float = 2.0) -> None:
        self._client = client
        self._warehouse_id = warehouse_id
        self._poll_seconds = poll_seconds

    def execute(self, sql: str, params: Mapping[str, str | None]) -> list[Row]:
        statements = self._client.statement_execution
        parameters = [StatementParameterListItem(name=name, value=value, type="STRING") for name, value in params.items()]
        resp = statements.execute_statement(
            warehouse_id=self._warehouse_id, statement=sql, parameters=parameters, wait_timeout="30s"
        )
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(self._poll_seconds)
            resp = statements.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            message = resp.status.error.message if resp.status.error else resp.status.state
            raise LakehouseError(f"Databricks statement failed: {message}")
        columns = [column.name for column in resp.manifest.schema.columns] if resp.manifest else []
        rows = resp.result.data_array if resp.result and resp.result.data_array else []
        return [dict(zip(columns, row)) for row in rows]


@dataclass(frozen=True)
class CustomerRecord:
    email: str
    profile: CustomerProfile


@dataclass(frozen=True)
class ProductStats:
    category: str
    return_rate: float


@dataclass(frozen=True)
class DecisionLogEntry:
    decision_id: str
    decided_at: datetime
    customer_id: str
    customer_email: str
    order_id: str
    decision: InterventionDecision
    policy_adjustments: tuple[str, ...]


@dataclass(frozen=True)
class PendingDecision:
    decision_id: str
    order_id: str
    customer_email: str


class LakehouseStore:
    def __init__(self, executor: SqlExecutor, catalog: str, schema: str) -> None:
        self._executor = executor
        self._schema = f"`{catalog}`.`{schema}`"

    @classmethod
    def from_settings(cls, settings: DatabricksSettings) -> "LakehouseStore":
        return cls(WarehouseExecutor(workspace_client(settings), settings.warehouse_id), settings.catalog, settings.schema)

    def customer_by_email(self, email: str) -> CustomerRecord | None:
        rows = self._executor.execute(
            f"SELECT * FROM {self._schema}.customer_return_profile WHERE lower(email) = lower(:email) LIMIT 1",
            {"email": email},
        )
        if not rows:
            return None
        row = rows[0]
        return CustomerRecord(
            email=row["email"] or email,
            profile=CustomerProfile(
                customer_id=row["customer_id"],
                loyalty_tier=row["loyalty_tier"],
                preferred_channel=row["preferred_channel"],
                marketing_opt_in=row["marketing_opt_in"] == "true",
                lifetime_value=float(row["lifetime_value"] or 0),
                lifetime_orders=int(row["lifetime_orders"] or 0),
                historical_return_rate=float(row["historical_return_rate"] or 0),
                churn_risk=float(row["churn_probability"]) if row["churn_probability"] is not None else None,
                support_cases_30d=int(row["support_cases_30d"] or 0),
            ),
        )

    def product_stats(self, product_ids: Sequence[str]) -> dict[str, ProductStats]:
        if not product_ids:
            return {}
        rows = self._executor.execute(
            f"SELECT product_id, category, return_rate FROM {self._schema}.product_return_stats "
            "WHERE array_contains(from_json(:ids, 'array<string>'), product_id)",
            {"ids": json.dumps(list(product_ids))},
        )
        return {
            row["product_id"]: ProductStats(category=row["category"], return_rate=float(row["return_rate"] or 0))
            for row in rows
        }

    def prior_interventions(self, customer_id: str) -> tuple[PriorIntervention, ...]:
        rows = self._executor.execute(
            f"SELECT order_id, intervention_type, outcome FROM {self._schema}.intervention_log "
            "WHERE customer_id = :customer_id AND outcome <> 'pending' ORDER BY decided_at DESC LIMIT 20",
            {"customer_id": customer_id},
        )
        return tuple(
            PriorIntervention(
                order_id=row["order_id"],
                intervention_type=InterventionType(row["intervention_type"]),
                item_returned=row["outcome"] == "returned",
            )
            for row in rows
        )

    def decided_order_ids(self, order_ids: Sequence[str]) -> frozenset[str]:
        if not order_ids:
            return frozenset()
        rows = self._executor.execute(
            f"SELECT DISTINCT order_id FROM {self._schema}.intervention_log "
            "WHERE array_contains(from_json(:ids, 'array<string>'), order_id)",
            {"ids": json.dumps(list(order_ids))},
        )
        return frozenset(row["order_id"] for row in rows)

    def log_decision(self, entry: DecisionLogEntry) -> None:
        decision = entry.decision
        self._executor.execute(
            f"INSERT INTO {self._schema}.intervention_log (decision_id, decided_at, customer_id, customer_email, "
            "order_id, target_sku, risk_level, risk_score, intervention_type, channel, incentive_percent, rationale, "
            "policy_adjustments, outcome, outcome_at) VALUES (:decision_id, CAST(:decided_at AS TIMESTAMP), "
            ":customer_id, :customer_email, :order_id, :target_sku, :risk_level, CAST(:risk_score AS DOUBLE), "
            ":intervention_type, :channel, CAST(:incentive_percent AS DOUBLE), :rationale, "
            "from_json(:policy_adjustments, 'array<string>'), 'pending', NULL)",
            {
                "decision_id": entry.decision_id,
                "decided_at": entry.decided_at.isoformat(),
                "customer_id": entry.customer_id,
                "customer_email": entry.customer_email,
                "order_id": entry.order_id,
                "target_sku": decision.target_sku,
                "risk_level": decision.risk_level.value,
                "risk_score": str(decision.risk_score),
                "intervention_type": decision.intervention_type.value,
                "channel": decision.channel.value,
                "incentive_percent": str(decision.incentive.percent_of_item_price) if decision.incentive else None,
                "rationale": decision.rationale,
                "policy_adjustments": json.dumps(list(entry.policy_adjustments)),
            },
        )

    def pending_decisions(self) -> list[PendingDecision]:
        rows = self._executor.execute(
            f"SELECT decision_id, order_id, customer_email FROM {self._schema}.intervention_log "
            "WHERE outcome = 'pending'",
            {},
        )
        return [PendingDecision(row["decision_id"], row["order_id"], row["customer_email"]) for row in rows]

    def record_outcome(self, decision_id: str, outcome: Outcome) -> None:
        self._executor.execute(
            f"UPDATE {self._schema}.intervention_log SET outcome = :outcome, outcome_at = current_timestamp() "
            "WHERE decision_id = :decision_id AND outcome = 'pending'",
            {"outcome": outcome, "decision_id": decision_id},
        )
