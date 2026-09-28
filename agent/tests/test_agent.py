from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeModel, make_decision
from returnguard.agent import ReturnGuardAgent, build_context
from returnguard.bloomreach import INTERVENTION_EVENT
from returnguard.context import CustomerProfile, PriorIntervention
from returnguard.enums import InterventionType
from returnguard.lakehouse import CustomerRecord, LakehouseError, PendingDecision, ProductStats
from returnguard.shopify import ShopifyLineItem, ShopifyOrder

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


def make_order(**overrides):
    base = dict(
        id="gid://shopify/Order/1",
        name="#1001",
        processed_at=NOW - timedelta(days=4),
        customer_email="ava@example.test",
        customer_id="gid://shopify/Customer/9",
        delivered=True,
        return_status="NO_RETURN",
        currency="USD",
        total=59.0,
        line_items=(ShopifyLineItem("PROD-004", "Summit Skincare 04", "uncategorized", 1, 59.0),),
    )
    return ShopifyOrder(**{**base, **overrides})


RECORD = CustomerRecord(
    email="ava@example.test",
    profile=CustomerProfile(
        customer_id="CUST-0023",
        marketing_opt_in=True,
        lifetime_value=16057.93,
        lifetime_orders=30,
        historical_return_rate=0.0667,
    ),
)


class FakeShopify:
    def __init__(self, orders, by_id=None):
        self.orders = orders
        self.by_id = by_id or {}
        self.discounts = []

    def recent_orders(self, since):
        return self.orders

    def orders_by_id(self, ids):
        return {i: self.by_id[i] for i in ids if i in self.by_id}

    def create_keep_discount(self, code, percent, customer_id, starts_at, ends_at):
        self.discounts.append((code, percent, customer_id))
        return "gid://discount/1"


class FakeLakehouse:
    def __init__(self, record=RECORD, decided=frozenset(), pending=(), fail_on_log=False):
        self.record = record
        self.decided = decided
        self.pending = list(pending)
        self.fail_on_log = fail_on_log
        self.logged = []
        self.outcomes = []

    def customer_by_email(self, email):
        return self.record

    def product_stats(self, ids):
        return {"PROD-004": ProductStats("Beauty", 0.0877)}

    def prior_interventions(self, customer_id):
        return (PriorIntervention(order_id="0977", intervention_type=InterventionType.USAGE_TIPS, item_returned=True),)

    def decided_order_ids(self, ids):
        return self.decided

    def log_decision(self, entry):
        if self.fail_on_log:
            raise LakehouseError("warehouse offline")
        self.logged.append(entry)

    def pending_decisions(self):
        return self.pending

    def record_outcome(self, decision_id, outcome):
        self.outcomes.append((decision_id, outcome))


class FakeBloomreach:
    def __init__(self, events=()):
        self.events = list(events)
        self.profile_updates = []
        self.tracked = []

    def customer_events(self, key, types):
        return self.events

    def update_customer(self, key, properties):
        self.profile_updates.append((key, properties))

    def track_event(self, key, event_type, properties, timestamp):
        self.tracked.append((key, event_type, properties))


def make_agent(shopify, lakehouse, bloomreach, decision):
    return ReturnGuardAgent(
        shopify=shopify,
        lakehouse=lakehouse,
        bloomreach=bloomreach,
        model=FakeModel(decision.model_dump_json()),
        now=lambda: NOW,
        new_id=lambda: "abc123def",
    )


def test_run_decides_logs_then_delivers_through_bloomreach():
    shopify, lakehouse, bloomreach = FakeShopify([make_order()]), FakeLakehouse(), FakeBloomreach()
    decision = make_decision(target_sku="PROD-004")
    report = make_agent(shopify, lakehouse, bloomreach, decision).run_once()

    assert report.orders[0].status == "decided"
    assert "exchange_offer via sms" in report.orders[0].detail
    assert lakehouse.logged[0].order_id == "gid://shopify/Order/1"
    assert lakehouse.logged[0].customer_id == "CUST-0023"
    assert bloomreach.profile_updates[0][1]["returnguard_risk_level"] == "high"
    key, event_type, props = bloomreach.tracked[0]
    assert (key, event_type) == ("ava@example.test", INTERVENTION_EVENT)
    assert props["decision_id"] == "abc123def"
    assert props["discount_code"] is None
    assert shopify.discounts == []


def test_keep_incentive_creates_customer_scoped_shopify_code():
    shopify, lakehouse, bloomreach = FakeShopify([make_order()]), FakeLakehouse(), FakeBloomreach()
    incentive = {"incentive_type": "next_order_discount", "percent_of_item_price": 10, "justification": "VIP"}
    decision = make_decision(intervention_type="keep_incentive", incentive=incentive, target_sku="PROD-004")
    make_agent(shopify, lakehouse, bloomreach, decision).run_once()

    assert shopify.discounts == [("RG-1001-ABC123", 10.0, "gid://shopify/Customer/9")]
    assert bloomreach.tracked[0][2]["discount_code"] == "RG-1001-ABC123"


def test_no_action_updates_profile_but_sends_nothing():
    shopify, lakehouse, bloomreach = FakeShopify([make_order()]), FakeLakehouse(), FakeBloomreach()
    decision = make_decision(risk_level="low", intervention_type="none", channel="none", target_sku=None, message=None)
    report = make_agent(shopify, lakehouse, bloomreach, decision).run_once()

    assert report.orders[0].status == "decided"
    assert len(bloomreach.profile_updates) == 1
    assert bloomreach.tracked == []
    assert len(lakehouse.logged) == 1


@pytest.mark.parametrize(
    ("order", "decided", "reason"),
    [
        (make_order(), frozenset({"gid://shopify/Order/1"}), "already decided"),
        (make_order(return_status="RETURN_REQUESTED"), frozenset(), "return already started"),
        (make_order(customer_email=None), frozenset(), "no customer email"),
        (make_order(processed_at=NOW - timedelta(days=45)), frozenset(), "return window closed"),
        (make_order(line_items=()), frozenset(), "no line items"),
    ],
)
def test_orders_are_skipped_with_a_reason(order, decided, reason):
    bloomreach = FakeBloomreach()
    report = make_agent(FakeShopify([order]), FakeLakehouse(decided=decided), bloomreach, make_decision()).run_once()
    assert report.orders[0].status == "skipped"
    assert reason in report.orders[0].detail
    assert bloomreach.tracked == []


def test_policy_block_is_explained_in_the_report():
    opted_out = CustomerRecord(RECORD.email, RECORD.profile.model_copy(update={"marketing_opt_in": False}))
    bloomreach = FakeBloomreach()
    agent = make_agent(FakeShopify([make_order()]), FakeLakehouse(record=opted_out), bloomreach, make_decision())
    report = agent.run_once()

    assert "none via none [policy: Customer has not opted in" in report.orders[0].detail
    assert bloomreach.tracked == []


def test_unknown_customer_is_skipped():
    report = make_agent(FakeShopify([make_order()]), FakeLakehouse(record=None), FakeBloomreach(), make_decision()).run_once()
    assert report.orders[0].detail == "customer not found in the Lakehouse"


def test_failure_on_one_order_is_reported_and_nothing_is_sent():
    bloomreach = FakeBloomreach()
    agent = make_agent(FakeShopify([make_order()]), FakeLakehouse(fail_on_log=True), bloomreach, make_decision())
    report = agent.run_once()
    assert report.orders[0].status == "failed"
    assert "warehouse offline" in report.orders[0].detail
    assert bloomreach.tracked == []


def test_resolve_outcomes_records_returned_and_kept_and_waits_otherwise():
    returned = make_order(id="o-1", name="#1", return_status="RETURNED")
    kept = make_order(id="o-2", name="#2", processed_at=NOW - timedelta(days=31))
    still_open = make_order(id="o-3", name="#3")
    pending = [
        PendingDecision("d-1", "o-1", "a@example.test"),
        PendingDecision("d-2", "o-2", "b@example.test"),
        PendingDecision("d-3", "o-3", "c@example.test"),
        PendingDecision("d-4", "o-missing", "d@example.test"),
    ]
    lakehouse, bloomreach = FakeLakehouse(pending=pending), FakeBloomreach()
    shopify = FakeShopify([], by_id={"o-1": returned, "o-2": kept, "o-3": still_open})

    report = make_agent(shopify, lakehouse, bloomreach, make_decision()).run_once()

    assert report.resolved == ("#1: returned", "#2: kept")
    assert lakehouse.outcomes == [("d-1", "returned"), ("d-2", "kept")]
    assert [t[1] for t in bloomreach.tracked] == ["returnguard_outcome", "returnguard_outcome"]


def test_build_context_joins_all_three_sources():
    events = [
        {
            "type": "page_visit",
            "timestamp": (NOW - timedelta(days=1)).timestamp(),
            "properties": {"location": "https://shop.test/pages/returns"},
        }
    ]
    prior = (PriorIntervention(order_id="0977", intervention_type=InterventionType.USAGE_TIPS, item_returned=True),)
    context = build_context(make_order(), RECORD, {"PROD-004": ProductStats("Beauty", 0.0877)}, events, prior, NOW)

    assert context.order.order_id == "#1001"
    assert context.order.days_since_order == 4
    assert context.order.days_left_in_return_window == 26
    assert context.order.line_items[0].category == "Beauty"
    assert context.order.line_items[0].sku_return_rate == pytest.approx(0.0877)
    assert context.engagement.visited_return_policy_page is True
    assert context.prior_interventions == prior


def test_build_context_defaults_for_unknown_sku():
    order = make_order(line_items=(ShopifyLineItem("", "Gift card", "gift", 0, 25.0),))
    context = build_context(order, RECORD, {}, [], (), NOW)
    item = context.order.line_items[0]
    assert (item.sku, item.category, item.sku_return_rate, item.quantity) == ("Gift card", "gift", 0.0, 1)
