"""Demo the learning loop: the customer returns an order anyway, then buys again.

SIMULATED customer behaviour (disclosed in the submission): creates a real Shopify return on the given demo
order and, with --next-order, a new test order for the same customer, placed a day ago, followed by a refund-policy
visit in Bloomreach (tagged simulated). On the next `returnguard run` the agent records the outcome in Databricks
and reads it back when deciding on the new order, so it has to pick something other than what already failed.

    uv run --env-file .env python scripts/simulate_return.py 1001 --next-order
"""

import argparse
from datetime import datetime, timedelta, timezone

from returnguard.bloomreach import BloomreachClient
from returnguard.config import load_bloomreach_settings, load_shopify_settings
from returnguard.shopify import ShopifyClient

SITE = "https://frontier-nvj3lkxp.myshopify.com"
NEXT_ORDER_AGE = timedelta(days=1)
SIGNAL_AGE = timedelta(hours=6)

ORDER_QUERY = """
query Order($q: String!) {
  orders(first: 1, query: $q) {
    nodes {
      id name email returnStatus
      customer { id firstName lastName }
      fulfillments { fulfillmentLineItems(first: 20) { nodes { id quantity lineItem { sku title originalUnitPriceSet { shopMoney { amount } } } } } }
    }
  }
}
"""

RETURN_CREATE = """
mutation Return($input: ReturnInput!) {
  returnCreate(returnInput: $input) {
    return { id status }
    userErrors { field message }
  }
}
"""

ORDER_CREATE = """
mutation NextOrder($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order { id name }
    userErrors { field message }
  }
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("order_number", help="Demo order number, e.g. 1001")
    parser.add_argument("--next-order", action="store_true", help="Also place a new order for the same customer")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    shopify = ShopifyClient.from_settings(load_shopify_settings())
    nodes = shopify.graphql(ORDER_QUERY, {"q": f"name:{args.order_number}"})["orders"]["nodes"]
    if not nodes:
        raise SystemExit(f"Order #{args.order_number} not found")
    order = nodes[0]
    lines = [line for f in order["fulfillments"] for line in f["fulfillmentLineItems"]["nodes"]]
    if not lines:
        raise SystemExit(f"{order['name']} has no fulfilled items to return")

    if order["returnStatus"] == "NO_RETURN":
        result = shopify.graphql(
            RETURN_CREATE,
            {
                "input": {
                    "orderId": order["id"],
                    "requestedAt": now.isoformat(),
                    "returnLineItems": [
                        {
                            "fulfillmentLineItemId": line["id"],
                            "quantity": line["quantity"],
                            "returnReasonNote": "Simulated for the ReturnGuard demo",
                        }
                        for line in lines
                    ],
                }
            },
        )["returnCreate"]
        if result["userErrors"]:
            raise SystemExit(f"returnCreate failed: {result['userErrors']}")
        print(f"{order['name']}: return created ({result['return']['status']})")
    else:
        print(f"{order['name']}: return already exists ({order['returnStatus']})")

    if args.next_order:
        customer = order["customer"]
        next_order = {
            "email": order["email"],
            "customer": {"toAssociate": {"id": customer["id"]}},
            "lineItems": [
                {
                    "title": line["lineItem"]["title"],
                    "sku": line["lineItem"]["sku"],
                    "quantity": 1,
                    "priceSet": {
                        "shopMoney": {
                            "amount": line["lineItem"]["originalUnitPriceSet"]["shopMoney"]["amount"],
                            "currencyCode": "USD",
                        }
                    },
                }
                for line in lines
            ],
            "processedAt": (now - NEXT_ORDER_AGE).isoformat(),
            "financialStatus": "PAID",
            "fulfillmentStatus": "FULFILLED",
            "test": True,
            "tags": ["returnguard-demo", "persona:repeat"],
        }
        created = shopify.graphql(
            ORDER_CREATE, {"order": next_order, "options": {"sendReceipt": False, "sendFulfillmentReceipt": False}}
        )["orderCreate"]
        if created["userErrors"]:
            raise SystemExit(f"orderCreate failed: {created['userErrors']}")
        print(f"{customer['firstName']} bought again: {created['order']['name']} (placed {NEXT_ORDER_AGE.days}d ago)")

        bloomreach = BloomreachClient.from_settings(load_bloomreach_settings())
        visit_at = now - SIGNAL_AGE
        bloomreach.track_event(order["email"], "session_start", {"simulated": True}, visit_at)
        bloomreach.track_event(
            order["email"],
            "page_visit",
            {"location": f"{SITE}/policies/refund-policy", "simulated": True},
            visit_at + timedelta(minutes=2),
        )
        print(f"...and read the refund policy {SIGNAL_AGE.seconds // 3600}h ago (simulated Bloomreach event)")


if __name__ == "__main__":
    main()
