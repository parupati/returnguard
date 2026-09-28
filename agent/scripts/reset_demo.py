"""Clear ReturnGuard's decisions for the demo orders so the agent can be run fresh (e.g. while recording the demo).

Deletes only intervention_log rows whose order is a Shopify order tagged `returnguard-demo`.
Orders, customers and Bloomreach events are left untouched.

    uv run --env-file .env python scripts/reset_demo.py
"""

import json

from databricks.sdk import WorkspaceClient

from returnguard.config import load_databricks_settings, load_shopify_settings
from returnguard.lakehouse import WarehouseExecutor
from returnguard.shopify import ShopifyClient

DEMO_ORDERS = 'query { orders(first: 50, query: "tag:returnguard-demo") { nodes { id name } } }'


def main() -> None:
    shopify = ShopifyClient.from_settings(load_shopify_settings())
    orders = shopify.graphql(DEMO_ORDERS, {})["orders"]["nodes"]
    if not orders:
        print("No demo orders found.")
        return

    db = load_databricks_settings()
    executor = WarehouseExecutor(WorkspaceClient(host=db.host, auth_type="external-browser"), db.warehouse_id)
    executor.execute(
        f"DELETE FROM `{db.catalog}`.`{db.schema}`.intervention_log "
        "WHERE array_contains(from_json(:ids, 'array<string>'), order_id)",
        {"ids": json.dumps([order["id"] for order in orders])},
    )
    print(f"Cleared decisions for demo orders: {[order['name'] for order in orders]}")


if __name__ == "__main__":
    main()
