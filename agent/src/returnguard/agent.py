"""The autonomous loop.

Signal: Shopify orders + Databricks features + Bloomreach engagement.
Reason: Gemini, then code-enforced policy.
Act:    Bloomreach profile update and intervention event (a scenario delivers it); Shopify discount code if earned.
Learn:  every decision and its eventual outcome is written to Databricks and read back on the next run.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import ValidationError

from returnguard.bloomreach import INTERVENTION_EVENT, BloomreachClient, BloomreachError
from returnguard.context import LineItem, OrderSnapshot, ReturnRiskContext
from returnguard.engagement import ENGAGEMENT_EVENT_TYPES, summarize_engagement
from returnguard.enums import InterventionType
from returnguard.lakehouse import CustomerRecord, DecisionLogEntry, LakehouseError, LakehouseStore, ProductStats
from returnguard.policy import PolicyResult
from returnguard.reasoning import DecisionModel, ReasoningError, decide
from returnguard.shopify import ShopifyClient, ShopifyError, ShopifyOrder

logger = logging.getLogger(__name__)

RETURN_WINDOW_DAYS = 30
LOOKBACK_DAYS = 30
INCENTIVE_VALID_DAYS = 14
OUTCOME_EVENT = "returnguard_outcome"

AGENT_ERRORS = (ReasoningError, LakehouseError, BloomreachError, ShopifyError, ValidationError)


@dataclass(frozen=True)
class OrderOutcome:
    order_name: str
    status: str
    detail: str


@dataclass(frozen=True)
class RunReport:
    resolved: tuple[str, ...]
    orders: tuple[OrderOutcome, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid4().hex


class ReturnGuardAgent:
    def __init__(
        self,
        shopify: ShopifyClient,
        lakehouse: LakehouseStore,
        bloomreach: BloomreachClient,
        model: DecisionModel,
        now: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self._shopify = shopify
        self._lakehouse = lakehouse
        self._bloomreach = bloomreach
        self._model = model
        self._now = now
        self._new_id = new_id

    def run_once(self) -> RunReport:
        resolved = self.resolve_outcomes()
        now = self._now()
        orders = self._shopify.recent_orders(now - timedelta(days=LOOKBACK_DAYS))
        decided = self._lakehouse.decided_order_ids([order.id for order in orders])
        return RunReport(resolved, tuple(self._process(order, decided, now) for order in orders))

    def resolve_outcomes(self) -> tuple[str, ...]:
        pending = self._lakehouse.pending_decisions()
        orders = self._shopify.orders_by_id([p.order_id for p in pending])
        now = self._now()
        resolved = []
        for item in pending:
            order = orders.get(item.order_id)
            if order is None:
                continue
            if order.return_started:
                outcome = "returned"
            elif now - order.processed_at > timedelta(days=RETURN_WINDOW_DAYS):
                outcome = "kept"
            else:
                continue
            self._lakehouse.record_outcome(item.decision_id, outcome)
            self._bloomreach.track_event(
                item.customer_email,
                OUTCOME_EVENT,
                {"decision_id": item.decision_id, "order_name": order.name, "outcome": outcome},
                now,
            )
            resolved.append(f"{order.name}: {outcome}")
        return tuple(resolved)

    def _process(self, order: ShopifyOrder, decided: frozenset[str], now: datetime) -> OrderOutcome:
        skip = _skip_reason(order, decided, now)
        if skip:
            return OrderOutcome(order.name, "skipped", skip)
        try:
            return self._decide_and_act(order, now)
        except AGENT_ERRORS as exc:
            logger.exception("ReturnGuard failed on order %s", order.name)
            return OrderOutcome(order.name, "failed", str(exc))

    def _decide_and_act(self, order: ShopifyOrder, now: datetime) -> OrderOutcome:
        record = self._lakehouse.customer_by_email(order.customer_email or "")
        if record is None:
            return OrderOutcome(order.name, "skipped", "customer not found in the Lakehouse")

        context = build_context(
            order,
            record,
            self._lakehouse.product_stats([item.sku for item in order.line_items if item.sku]),
            self._bloomreach.customer_events(record.email, ENGAGEMENT_EVENT_TYPES),
            self._lakehouse.prior_interventions(record.profile.customer_id),
            now,
        )
        result = decide(context, self._model)
        decision_id = self._new_id()
        # Log before acting: a failed delivery must never lead to the customer being contacted twice.
        self._lakehouse.log_decision(
            DecisionLogEntry(
                decision_id=decision_id,
                decided_at=now,
                customer_id=record.profile.customer_id,
                customer_email=record.email,
                order_id=order.id,
                decision=result.decision,
                policy_adjustments=result.adjustments,
            )
        )
        self._act(order, record, result, decision_id, now)
        decision = result.decision
        policy_note = f" [policy: {' '.join(result.adjustments)}]" if result.adjustments else ""
        return OrderOutcome(
            order.name,
            "decided",
            f"{decision.risk_level.value} risk ({decision.risk_score:.2f}) -> "
            f"{decision.intervention_type.value} via {decision.channel.value}{policy_note}",
        )

    def _act(
        self, order: ShopifyOrder, record: CustomerRecord, result: PolicyResult, decision_id: str, now: datetime
    ) -> None:
        decision = result.decision
        self._bloomreach.update_customer(
            record.email,
            {
                "returnguard_risk_level": decision.risk_level.value,
                "returnguard_risk_score": decision.risk_score,
                "returnguard_last_order": order.name,
                "returnguard_last_decision": decision.intervention_type.value,
            },
        )
        if decision.intervention_type is InterventionType.NONE or decision.message is None:
            return

        discount_code = None
        if decision.incentive is not None and order.customer_id:
            discount_code = f"RG-{order.name.lstrip('#')}-{decision_id[:6].upper()}"
            self._shopify.create_keep_discount(
                discount_code,
                decision.incentive.percent_of_item_price,
                order.customer_id,
                now,
                now + timedelta(days=INCENTIVE_VALID_DAYS),
            )

        self._bloomreach.track_event(
            record.email,
            INTERVENTION_EVENT,
            {
                "decision_id": decision_id,
                "order_name": order.name,
                "intervention_type": decision.intervention_type.value,
                "channel": decision.channel.value,
                "target_sku": decision.target_sku,
                "risk_level": decision.risk_level.value,
                "risk_score": decision.risk_score,
                "message_subject": decision.message.subject,
                "message_body": decision.message.body,
                "cta_text": decision.message.cta_text,
                "discount_code": discount_code,
                "discount_percent": decision.incentive.percent_of_item_price if decision.incentive else None,
            },
            now,
        )


def _skip_reason(order: ShopifyOrder, decided: frozenset[str], now: datetime) -> str | None:
    if order.id in decided:
        return "already decided"
    if order.return_started:
        return f"return already started ({order.return_status})"
    if not order.customer_email:
        return "order has no customer email"
    if now - order.processed_at > timedelta(days=RETURN_WINDOW_DAYS):
        return "return window closed"
    if not order.line_items:
        return "order has no line items"
    return None


def build_context(
    order: ShopifyOrder,
    record: CustomerRecord,
    product_stats: Mapping[str, ProductStats],
    events: Sequence[Mapping],
    prior_interventions: tuple,
    now: datetime,
) -> ReturnRiskContext:
    days_since = max((now - order.processed_at).days, 0)
    line_items = tuple(
        LineItem(
            sku=item.sku or item.title,
            product_title=item.title,
            category=product_stats[item.sku].category if item.sku in product_stats else item.category,
            unit_price=item.unit_price,
            quantity=max(item.quantity, 1),
            sku_return_rate=product_stats[item.sku].return_rate if item.sku in product_stats else 0.0,
        )
        for item in order.line_items
    )
    return ReturnRiskContext(
        customer=record.profile,
        order=OrderSnapshot(
            order_id=order.name,
            placed_at=order.processed_at,
            currency=order.currency,
            total_value=order.total,
            delivered=order.delivered,
            days_since_order=days_since,
            days_left_in_return_window=RETURN_WINDOW_DAYS - days_since,
            line_items=line_items,
        ),
        engagement=summarize_engagement(events, order.processed_at, now),
        prior_interventions=prior_interventions,
    )
