"""Seed the demo: Shopify test orders and Bloomreach storefront behaviour for three real Databricks customers.

SIMULATED, and disclosed as such in the submission: the orders are Shopify test orders (Bogus gateway) and the
Bloomreach events stand in for storefront tracking the dev store does not have. Customers, products, prices,
return rates and churn scores all come from the hackathon's Databricks data.

Idempotent: customers that already have a demo order are skipped.

    uv run --env-file .env python scripts/seed_demo.py
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from databricks.sdk import WorkspaceClient

from returnguard.bloomreach import BloomreachClient
from returnguard.config import load_bloomreach_settings, load_databricks_settings, load_shopify_settings
from returnguard.lakehouse import WarehouseExecutor
from returnguard.shopify import ShopifyClient

DEMO_TAG = "returnguard-demo"
SITE = "https://frontier-nvj3lkxp.myshopify.com"

PERSONA_SQL = {
    "at_risk": "p.marketing_opt_in AND p.refunded_orders > 0 ORDER BY p.historical_return_rate DESC, p.support_cases_30d DESC",
    "loyal": "p.marketing_opt_in AND p.refunded_orders = 0 ORDER BY p.lifetime_value DESC",
    "opted_out": "NOT p.marketing_opt_in ORDER BY p.historical_return_rate DESC",
}

PERSONA_ORDERS = {
    "at_risk": {"days_ago": 3, "products": ["PROD-004"]},
    "loyal": {"days_ago": 5, "products": ["PROD-039", "PROD-001"]},
    "opted_out": {"days_ago": 2, "products": ["PROD-004"]},
}

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
            r = rows[0]
            personas.append(Persona(key, r["customer_id"], r["email"], r["first_name"], r["last_name"]))
    return personas


def load_products(executor: WarehouseExecutor, catalog: str, schema: str) -> dict[str, dict]:
    rows = executor.execute(
        f"SELECT product_id, product_name, category, CAST(list_price AS STRING) AS list_price "
        f"FROM `{catalog}`.`{schema}`.product_return_stats",
        {},
    )
    return {r["product_id"]: r for r in rows}


def create_order(shopify: ShopifyClient, persona: Persona, products: dict[str, dict], now: datetime) -> str | None:
    existing = shopify.graphql(EXISTING_DEMO_ORDER, {"q": f"tag:{DEMO_TAG} AND email:{persona.email}"})
    if existing["orders"]["nodes"]:
        print(f"  {persona.key}: demo order {existing['orders']['nodes'][0]['name']} already exists, skipping")
        return None
    plan = PERSONA_ORDERS[persona.key]
    line_items = [
        {
            "title": products[pid]["product_name"],
            "sku": pid,
            "quantity": 1,
            "priceSet": {"shopMoney": {"amount": products[pid]["list_price"], "currencyCode": "USD"}},
        }
        for pid in plan["products"]
    ]
    order = {
        "email": persona.email,
        "customer": {"toUpsert": {"email": persona.email, "firstName": persona.first_name, "lastName": persona.last_name}},
        "processedAt": (now - timedelta(days=plan["days_ago"])).isoformat(),
        "lineItems": line_items,
        "financialStatus": "PAID",
        "fulfillmentStatus": "FULFILLED",
        "test": True,
        "tags": [DEMO_TAG, f"persona:{persona.key}"],
    }
    data = shopify.graphql(ORDER_CREATE, {"order": order, "options": {"sendReceipt": False, "sendFulfillmentReceipt": False}})
    result = data["orderCreate"]
    if result["userErrors"]:
        raise SystemExit(f"orderCreate failed for {persona.key}: {result['userErrors']}")
    created = result["order"]
    print(f"  {persona.key}: created {created['name']} ({created['displayFulfillmentStatus']}) for {persona.customer_id}")
    return created["name"]


def seed_engagement(bloomreach: BloomreachClient, persona: Persona, now: datetime) -> None:
    ordered_at = now - timedelta(days=PERSONA_ORDERS[persona.key]["days_ago"])
    bloomreach.update_customer(
        persona.email,
        {"first_name": persona.first_name, "last_name": persona.last_name, "customer_id": persona.customer_id},
    )

    def track(event_type: str, at: datetime, **props) -> None:
        bloomreach.track_event(persona.email, event_type, {**props, "simulated": True}, at)

    def after_order(fraction: float, minutes: int = 0) -> datetime:
        """A point between the order and now, so post-order events are never future-dated."""
        return ordered_at + (now - ordered_at) * fraction + timedelta(minutes=minutes)

    if persona.key in ("at_risk", "opted_out"):
        for days in (50, 44, 38):
            track("campaign", now - timedelta(days=days), action_type="email", status="opened", campaign_name="Newsletter")
        track("session_start", after_order(0.3))
        track("page_visit", after_order(0.3, minutes=3), location=f"{SITE}/account/orders")
        track("session_start", after_order(0.7))
        track("page_visit", after_order(0.7, minutes=1), location=f"{SITE}/policies/refund-policy")
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
    print(f"  {persona.key}: seeded Bloomreach profile and simulated storefront events")


def main() -> None:
    now = datetime.now(timezone.utc)
    db = load_databricks_settings()
    executor = WarehouseExecutor(WorkspaceClient(host=db.host, auth_type="external-browser"), db.warehouse_id)
    shopify = ShopifyClient.from_settings(load_shopify_settings())
    bloomreach = BloomreachClient.from_settings(load_bloomreach_settings())

    personas = pick_personas(executor, db.catalog, db.schema, db.source_schema)
    products = load_products(executor, db.catalog, db.schema)
    print(f"Personas from Databricks: {[(p.key, p.customer_id) for p in personas]}")
    for persona in personas:
        create_order(shopify, persona, products, now)
        existing = bloomreach.customer_events(persona.email, ["session_start", "page_visit", "campaign"])
        if any((event.get("properties") or {}).get("simulated") for event in existing):
            print(f"  {persona.key}: Bloomreach events already seeded, skipping")
        else:
            seed_engagement(bloomreach, persona, now)


if __name__ == "__main__":
    main()
