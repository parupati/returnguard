"""Look inside each ReturnGuard module against the live systems. READ-ONLY: nothing is written anywhere.

    uv run --env-file .env python scripts/inspect_module.py config
    uv run --env-file .env python scripts/inspect_module.py databricks --customer CUST-0046
    uv run --env-file .env python scripts/inspect_module.py bloomreach --customer CUST-0046
    uv run --env-file .env python scripts/inspect_module.py shopify
    uv run --env-file .env python scripts/inspect_module.py gemini
    uv run --env-file .env python scripts/inspect_module.py preview 1001
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from databricks.sdk import WorkspaceClient

from returnguard import config
from returnguard.agent import LOOKBACK_DAYS, build_context
from returnguard.bloomreach import BloomreachClient
from returnguard.context import ReturnRiskContext
from returnguard.engagement import ENGAGEMENT_EVENT_TYPES, summarize_engagement
from returnguard.gemini import GeminiDecisionModel
from returnguard.lakehouse import LakehouseStore, WarehouseExecutor
from returnguard.reasoning import build_prompt, decide
from returnguard.shopify import ShopifyClient

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_context.json"


def heading(text: str) -> None:
    print(f"\n=== {text} ===")


def show(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def lakehouse() -> tuple[LakehouseStore, WarehouseExecutor, config.DatabricksSettings]:
    settings = config.load_databricks_settings()
    executor = WarehouseExecutor(WorkspaceClient(host=settings.host, auth_type="external-browser"), settings.warehouse_id)
    return LakehouseStore(executor, settings.catalog, settings.schema), executor, settings


def email_for(customer_id: str) -> str:
    _, executor, settings = lakehouse()
    rows = executor.execute(
        f"SELECT email FROM `{settings.catalog}`.`{settings.schema}`.customer_return_profile WHERE customer_id = :id",
        {"id": customer_id},
    )
    if not rows:
        raise SystemExit(f"{customer_id} not found in Databricks")
    return rows[0]["email"]


def cmd_config(_: argparse.Namespace) -> None:
    heading("Which settings load from agent/.env (secret values are never printed)")
    loaders = {
        "Gemini": (config.load_settings, ["gemini_model"]),
        "Databricks": (config.load_databricks_settings, ["host", "warehouse_id", "catalog", "schema", "source_schema"]),
        "Bloomreach": (config.load_bloomreach_settings, ["api_base_url", "customer_id_type"]),
        "Shopify": (config.load_shopify_settings, ["store_domain", "api_version"]),
    }
    for name, (loader, safe_fields) in loaders.items():
        try:
            settings = loader()
            print(f"{name:<11} OK   " + ", ".join(f"{f}={getattr(settings, f)}" for f in safe_fields))
        except config.ConfigError as exc:
            print(f"{name:<11} MISSING  {exc}")


def cmd_databricks(args: argparse.Namespace) -> None:
    store, executor, settings = lakehouse()
    email = email_for(args.customer)

    heading(f"customer_return_profile for {args.customer} (what Gemini learns about the customer)")
    show(store.customer_by_email(email).profile.model_dump())

    heading("product_return_stats: top 5 riskiest products (computed from real refunds)")
    rows = executor.execute(
        f"SELECT product_id, product_name, category, sold_lines, refunded_lines, return_rate "
        f"FROM `{settings.catalog}`.`{settings.schema}`.product_return_stats ORDER BY return_rate DESC LIMIT 5",
        {},
    )
    for r in rows:
        print(f"  {r['product_id']}  {r['product_name']:<24} {r['category']:<12} "
              f"{r['refunded_lines']}/{r['sold_lines']} refunded = {float(r['return_rate']):.1%}")

    heading(f"prior_interventions for {args.customer} (what the agent learned from past outcomes)")
    show([p.model_dump() for p in store.prior_interventions(args.customer)] or "none yet")

    heading("intervention_log: latest decisions")
    for r in executor.execute(
        f"SELECT decided_at, customer_id, risk_level, risk_score, intervention_type, channel, outcome "
        f"FROM `{settings.catalog}`.`{settings.schema}`.intervention_log ORDER BY decided_at DESC LIMIT 10",
        {},
    ):
        print(f"  {r['decided_at']}  {r['customer_id']}  {r['risk_level']:<6} {r['risk_score']:<5} "
              f"{r['intervention_type']:<17} {r['channel']:<9} outcome={r['outcome']}")


def cmd_bloomreach(args: argparse.Namespace) -> None:
    email = email_for(args.customer)
    client = BloomreachClient.from_settings(config.load_bloomreach_settings())
    events = client.customer_events(email, [*ENGAGEMENT_EVENT_TYPES, "returnguard_intervention", "returnguard_outcome"])

    heading(f"Raw Bloomreach events for {args.customer}: {len(events)} total")
    print("  by type:", dict(Counter(e.get("type") for e in events)))
    for e in sorted(events, key=lambda e: e.get("timestamp", 0))[-8:]:
        at = datetime.fromtimestamp(float(e.get("timestamp", 0)), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        props = {k: v for k, v in (e.get("properties") or {}).items() if k in ("location", "status", "campaign_name", "intervention_type", "channel", "outcome")}
        print(f"  {at}  {e.get('type'):<25} {props}")

    orders = [o for o in shopify().recent_orders(datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)) if o.customer_email == email]
    ordered_at = orders[0].processed_at if orders else datetime.now(timezone.utc) - timedelta(days=7)
    heading(f"engagement.py turns those events into signals (since order at {ordered_at:%Y-%m-%d %H:%M})")
    show(summarize_engagement(events, ordered_at, datetime.now(timezone.utc)).model_dump())


def shopify() -> ShopifyClient:
    return ShopifyClient.from_settings(config.load_shopify_settings())


def cmd_shopify(_: argparse.Namespace) -> None:
    orders = shopify().recent_orders(datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS))
    heading(f"Orders from the last {LOOKBACK_DAYS} days: {len(orders)} (what the agent scans each run)")
    for o in orders:
        items = ", ".join(f"{li.sku} x{li.quantity} @ {li.unit_price}" for li in o.line_items)
        print(f"  {o.name}  {o.processed_at:%Y-%m-%d}  {o.customer_email:<38} delivered={o.delivered!s:<5} "
              f"return={o.return_status:<16} [{items}]")


def cmd_gemini(_: argparse.Namespace) -> None:
    context = ReturnRiskContext.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    heading("Prompt sent to Gemini for the sample fixture (tests/fixtures/sample_context.json)")
    print("(The system instruction with the reasoning rules is in src/returnguard/reasoning.py)\n")
    print(build_prompt(context))
    result = decide(context, GeminiDecisionModel.from_settings(config.load_settings()))
    heading("Gemini's decision after policy")
    show(result.decision.model_dump(mode="json"))
    heading("Policy adjustments")
    show(list(result.adjustments) or "none: the decision passed every guardrail")


def cmd_preview(args: argparse.Namespace) -> None:
    now = datetime.now(timezone.utc)
    name = f"#{args.order.lstrip('#')}"
    orders = shopify().recent_orders(now - timedelta(days=LOOKBACK_DAYS))
    order = next((o for o in orders if o.name == name), None)
    if order is None:
        raise SystemExit(f"{name} not found in the last {LOOKBACK_DAYS} days")

    store, _, _ = lakehouse()
    record = store.customer_by_email(order.customer_email or "")
    if record is None:
        raise SystemExit(f"{order.customer_email} is not a Databricks customer")
    bloomreach = BloomreachClient.from_settings(config.load_bloomreach_settings())
    context = build_context(
        order,
        record,
        store.product_stats([li.sku for li in order.line_items if li.sku]),
        bloomreach.customer_events(record.email, ENGAGEMENT_EVENT_TYPES),
        store.prior_interventions(record.profile.customer_id),
        now,
    )
    heading(f"1. Context the agent assembled for {name} from Shopify + Databricks + Bloomreach")
    show(context.model_dump(mode="json"))

    result = decide(context, GeminiDecisionModel.from_settings(config.load_settings()))
    heading("2. Gemini's decision (after policy)")
    show(result.decision.model_dump(mode="json"))
    heading("3. Policy adjustments")
    show(list(result.adjustments) or "none: the decision passed every guardrail")
    print("\nDry run: nothing was logged to Databricks or sent to Bloomreach/Shopify.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config").set_defaults(func=cmd_config)
    for name, func in (("databricks", cmd_databricks), ("bloomreach", cmd_bloomreach)):
        p = sub.add_parser(name)
        p.add_argument("--customer", default="CUST-0046")
        p.set_defaults(func=func)
    sub.add_parser("shopify").set_defaults(func=cmd_shopify)
    sub.add_parser("gemini").set_defaults(func=cmd_gemini)
    preview = sub.add_parser("preview")
    preview.add_argument("order", help="Order number, e.g. 1001")
    preview.set_defaults(func=cmd_preview)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
