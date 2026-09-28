"""Seed the demo: Shopify test orders and Bloomreach storefront behaviour for real Databricks customers.

SIMULATED, and disclosed as such in the submission: the orders are Shopify test orders (Bogus gateway) and the
Bloomreach events stand in for storefront tracking the dev store does not have. Customers, products, prices,
return rates and churn scores all come from the hackathon's Databricks data.

Three hand-picked personas carry the demo narrative (#1001 at-risk, #1002 loyal, #1003 opted-out). --extra-orders
adds a crowd of other real customers, so a run shows the agent leaving most orders alone.

Idempotent: customers that already have a demo order, or already have simulated events, are skipped.

    uv run --env-file .env python scripts/seed_demo.py
    uv run --env-file .env python scripts/seed_demo.py --extra-orders 22
"""

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from returnguard.bloomreach import BloomreachClient
from returnguard.config import load_bloomreach_settings, load_databricks_settings, load_shopify_settings
from returnguard.lakehouse import WarehouseExecutor, workspace_client
from returnguard.shopify import ShopifyClient

DEMO_TAG = "returnguard-demo"
SITE = "https://frontier-nvj3lkxp.myshopify.com"

PERSONA_SQL = {
    "at_risk": "p.marketing_opt_in AND p.refunded_orders > 0 ORDER BY p.historical_return_rate DESC, p.support_cases_30d DESC",
    "loyal": "p.marketing_opt_in AND p.refunded_orders = 0 ORDER BY p.lifetime_value DESC",
    "opted_out": "NOT p.marketing_opt_in ORDER BY p.historical_return_rate DESC",
}

CROWD_PATTERNS = ("worried", "engaged", "exchange_browser", "quiet", "quiet")

# Dev stores allow roughly 5 new orders per minute.
THROTTLE_WAIT_SECONDS = 30
THROTTLE_RETRIES = 6

ORDER_CREATE = """
mutation SeedOrder($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order { id name displayFulfillmentStatus }
    userErrors { field message }
  }
}
"""

EXISTING_DEMO_ORDER = """
query Existing($q: String!) { orders(first: 1, query: $q) { nodes { id name } } }
"""


@dataclass(frozen=True)
class Persona:
    key: str
    customer_id: str
    email: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class OrderPlan:
    days_ago: int
    products: tuple[str, ...]
    pattern: str


PERSONA_PLANS = {
    "at_risk": OrderPlan(3, ("PROD-004",), "worried"),
    "loyal": OrderPlan(5, ("PROD-039", "PROD-001"), "engaged"),
    "opted_out": OrderPlan(2, ("PROD-004",), "worried"),
}


def _persona(key: str, row: dict) -> Persona:
    return Persona(key, row["customer_id"], row["email"], row["first_name"], row["last_name"])


def pick_personas(executor: WarehouseExecutor, catalog: str, schema: str, source: str) -> list[Persona]:
    personas = []
    for key, where_order in PERSONA_SQL.items():
        rows = executor.execute(
            f"SELECT p.customer_id, p.email, c.first_name, c.last_name "
            f"FROM `{catalog}`.`{schema}`.customer_return_profile p "
            f"JOIN `{catalog}`.`{source}`.customers c USING (customer_id) WHERE {where_order} LIMIT 1",
            {},
        )
        if rows:
            personas.append(_persona(key, rows[0]))
    return personas


def pick_crowd(
    executor: WarehouseExecutor, catalog: str, schema: str, source: str, count: int, exclude: list[str]
) -> list[Persona]:
    rows = executor.execute(
        f"SELECT p.customer_id, p.email, c.first_name, c.last_name "
        f"FROM `{catalog}`.`{schema}`.customer_return_profile p "
        f"JOIN `{catalog}`.`{source}`.customers c USING (customer_id) "
        f"WHERE NOT array_contains(from_json(:exclude, 'array<string>'), p.customer_id) "
        f"ORDER BY p.customer_id LIMIT {int(count)}",
        {"exclude": json.dumps(exclude)},
    )
    return [_persona("crowd", row) for row in rows]


def crowd_plan(index: int, products_by_risk: list[str]) -> OrderPlan:
    """Deterministic spread: products across the whole return-rate range, dates within the window."""
    size = len(products_by_risk)
    items = [products_by_risk[(index * 3) % size]]
    if index % 4 == 0:
        items.append(products_by_risk[(index * 3 + 17) % size])
    return OrderPlan(1 + index % 9, tuple(items), CROWD_PATTERNS[index % len(CROWD_PATTERNS)])


def load_products(executor: WarehouseExecutor, catalog: str, schema: str) -> dict[str, dict]:
    rows = executor.execute(
        f"SELECT product_id, product_name, category, CAST(list_price AS STRING) AS list_price, return_rate "
        f"FROM `{catalog}`.`{schema}`.product_return_stats",
        {},
    )
    return {r["product_id"]: r for r in rows}


def create_order(
    shopify: ShopifyClient, persona: Persona, plan: OrderPlan, products: dict[str, dict], now: datetime
) -> str | None:
    existing = shopify.graphql(EXISTING_DEMO_ORDER, {"q": f"tag:{DEMO_TAG} AND email:{persona.email}"})
    if existing["orders"]["nodes"]:
        print(f"  {persona.customer_id}: demo order {existing['orders']['nodes'][0]['name']} already exists, skipping")
        return None
    line_items = [
        {
            "title": products[pid]["product_name"],
            "sku": pid,
            "quantity": 1,
            "priceSet": {"shopMoney": {"amount": products[pid]["list_price"], "currencyCode": "USD"}},
        }
        for pid in plan.products
    ]
    order = {
        "email": persona.email,
        "customer": {"toUpsert": {"email": persona.email, "firstName": persona.first_name, "lastName": persona.last_name}},
        "processedAt": (now - timedelta(days=plan.days_ago)).isoformat(),
        "lineItems": line_items,
        "financialStatus": "PAID",
        "fulfillmentStatus": "FULFILLED",
        "test": True,
        "tags": [DEMO_TAG, f"persona:{persona.key}"],
    }
    for attempt in range(1, THROTTLE_RETRIES + 1):
        data = shopify.graphql(
            ORDER_CREATE, {"order": order, "options": {"sendReceipt": False, "sendFulfillmentReceipt": False}}
        )
        result = data["orderCreate"]
        throttled = any("too many attempts" in (e.get("message") or "").lower() for e in result["userErrors"])
        if not throttled:
            break
        print(f"  {persona.customer_id}: Shopify dev-store order limit hit, waiting {THROTTLE_WAIT_SECONDS}s "
              f"(attempt {attempt}/{THROTTLE_RETRIES})", flush=True)
        time.sleep(THROTTLE_WAIT_SECONDS)
    if result["userErrors"]:
        raise SystemExit(f"orderCreate failed for {persona.customer_id}: {result['userErrors']}")
    created = result["order"]
    print(f"  {persona.customer_id}: created {created['name']} [{', '.join(plan.products)}] "
          f"{plan.days_ago}d ago, behaviour={plan.pattern}")
    return created["name"]


def seed_engagement(bloomreach: BloomreachClient, persona: Persona, plan: OrderPlan, now: datetime) -> None:
    ordered_at = now - timedelta(days=plan.days_ago)
    bloomreach.update_customer(
        persona.email,
        {"first_name": persona.first_name, "last_name": persona.last_name, "customer_id": persona.customer_id},
    )
    if plan.pattern == "quiet":
        return

    def track(event_type: str, at: datetime, **props) -> None:
        bloomreach.track_event(persona.email, event_type, {**props, "simulated": True}, at)

    def after_order(fraction: float, minutes: int = 0) -> datetime:
        """A point between the order and now, so post-order events are never future-dated."""
        return ordered_at + (now - ordered_at) * fraction + timedelta(minutes=minutes)

    if plan.pattern == "worried":
        for days in (50, 44, 38):
            track("campaign", now - timedelta(days=days), action_type="email", status="opened", campaign_name="Newsletter")
        track("session_start", after_order(0.3))
        track("page_visit", after_order(0.3, minutes=3), location=f"{SITE}/account/orders")
        track("session_start", after_order(0.7))
        track("page_visit", after_order(0.7, minutes=1), location=f"{SITE}/policies/refund-policy")
    elif plan.pattern == "exchange_browser":
        track("session_start", after_order(0.5))
        track("page_visit", after_order(0.5, minutes=2), location=f"{SITE}/pages/exchanges")
    else:
        for days in (40, 20, 10):
            track("campaign", now - timedelta(days=days), action_type="email", status="opened", campaign_name="Newsletter")
        track("campaign", after_order(0.05), action_type="email", status="opened", campaign_name="Order confirmation")
        track(
            "campaign",
            after_order(0.4),
            action_type="email",
            status="clicked",
            campaign_name="Shipping update",
            url="https://carrier.test/track/demo",
        )
        track("session_start", after_order(0.8))


def seed(shopify: ShopifyClient, bloomreach: BloomreachClient, persona: Persona, plan: OrderPlan, products, now) -> None:
    create_order(shopify, persona, plan, products, now)
    existing = bloomreach.customer_events(persona.email, ["session_start", "page_visit", "campaign"])
    if any((event.get("properties") or {}).get("simulated") for event in existing):
        return
    seed_engagement(bloomreach, persona, plan, now)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extra-orders", type=int, default=0, help="Orders for additional real customers")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    db = load_databricks_settings()
    executor = WarehouseExecutor(workspace_client(db), db.warehouse_id)
    shopify = ShopifyClient.from_settings(load_shopify_settings())
    bloomreach = BloomreachClient.from_settings(load_bloomreach_settings())
    products = load_products(executor, db.catalog, db.schema)

    personas = pick_personas(executor, db.catalog, db.schema, db.source_schema)
    print(f"Demo personas: {[(p.key, p.customer_id) for p in personas]}")
    for persona in personas:
        seed(shopify, bloomreach, persona, PERSONA_PLANS[persona.key], products, now)

    if args.extra_orders > 0:
        products_by_risk = sorted(products, key=lambda pid: float(products[pid]["return_rate"] or 0), reverse=True)
        crowd = pick_crowd(
            executor, db.catalog, db.schema, db.source_schema, args.extra_orders, [p.customer_id for p in personas]
        )
        print(f"Adding orders for {len(crowd)} more customers:")
        for index, persona in enumerate(crowd):
            seed(shopify, bloomreach, persona, crowd_plan(index, products_by_risk), products, now)


if __name__ == "__main__":
    main()
