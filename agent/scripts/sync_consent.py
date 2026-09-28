"""Sync marketing consent from Databricks to Bloomreach for the demo customers.

Bloomreach suppresses campaign email to anyone without a consent record for the email's consent category. The
source of truth for consent is Databricks (`marketing_opt_in`). This records a Bloomreach `consent` event with
action `accept` only for demo customers who opted in; everyone else stays without consent and remains suppressed,
matching ReturnGuard's own consent rule.

    uv run --env-file .env python scripts/sync_consent.py            # category "other" (the scenario email's)
    uv run --env-file .env python scripts/sync_consent.py --category marketing
"""

import argparse
from datetime import datetime, timezone

from returnguard.bloomreach import BloomreachClient
from returnguard.config import load_bloomreach_settings, load_databricks_settings, load_shopify_settings
from returnguard.lakehouse import LakehouseStore
from returnguard.shopify import ShopifyClient

DEMO_CUSTOMERS = 'query { orders(first: 50, query: "tag:returnguard-demo") { nodes { email } } }'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", default="other", help="Bloomreach consent category used by the scenario email")
    args = parser.parse_args()

    orders = ShopifyClient.from_settings(load_shopify_settings()).graphql(DEMO_CUSTOMERS, {})["orders"]["nodes"]
    emails = sorted({o["email"] for o in orders if o["email"]})
    lakehouse = LakehouseStore.from_settings(load_databricks_settings())
    bloomreach = BloomreachClient.from_settings(load_bloomreach_settings())
    now = datetime.now(timezone.utc)

    granted, skipped = [], []
    for email in emails:
        record = lakehouse.customer_by_email(email)
        if record is None or not record.profile.marketing_opt_in:
            skipped.append(email)
            continue
        bloomreach.track_event(
            email,
            "consent",
            {
                "action": "accept",
                "category": args.category,
                "valid_until": "unlimited",
                "source": "databricks.marketing_opt_in",
                "message": "Synced from the Databricks customer profile by ReturnGuard",
            },
            now,
        )
        granted.append(record.profile.customer_id)
    print(f"Consent '{args.category}' recorded for {len(granted)} opted-in customers: {granted}")
    print(f"Left without consent (not opted in, or not in Databricks): {len(skipped)} {skipped}")


if __name__ == "__main__":
    main()
