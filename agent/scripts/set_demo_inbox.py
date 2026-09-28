"""Point every demo customer's Bloomreach `email` contact property at one real inbox.

The demo customers have undeliverable @example.test addresses, and Bloomreach sends campaign email to the `email`
property (not the `email_id` identifier). This redirects the demo customers only: their Shopify orders are tagged
`returnguard-demo`. Delivery still needs an email integration configured in Bloomreach.

    uv run --env-file .env python scripts/set_demo_inbox.py you@example.com
"""

import argparse
import re

from returnguard.bloomreach import BloomreachClient
from returnguard.config import load_bloomreach_settings, load_shopify_settings
from returnguard.shopify import ShopifyClient

DEMO_CUSTOMERS = 'query { orders(first: 50, query: "tag:returnguard-demo") { nodes { name email } } }'
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inbox", help="The inbox that should receive all demo emails")
    args = parser.parse_args()
    if not EMAIL.match(args.inbox):
        raise SystemExit(f"Not an email address: {args.inbox!r}")

    orders = ShopifyClient.from_settings(load_shopify_settings()).graphql(DEMO_CUSTOMERS, {})["orders"]["nodes"]
    customer_ids = sorted({order["email"] for order in orders if order["email"]})
    bloomreach = BloomreachClient.from_settings(load_bloomreach_settings())
    for customer_id in customer_ids:
        bloomreach.update_customer(customer_id, {"email": args.inbox})
    print(f"Redirected {len(customer_ids)} demo customers' email to the demo inbox: {customer_ids}")


if __name__ == "__main__":
    main()
