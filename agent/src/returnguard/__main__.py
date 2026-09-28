"""ReturnGuard command line.

  returnguard decide <context.json>   One Gemini decision for a saved order context (no side effects).
  returnguard run                      One full agent cycle across Shopify, Databricks, Bloomreach and Gemini.
  returnguard watch --interval 3600    Run the agent on a schedule until stopped.
"""

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from returnguard.config import ConfigError, load_settings
from returnguard.context import ReturnRiskContext
from returnguard.reasoning import DecisionModel, decide

DEFAULT_WATCH_INTERVAL_SECONDS = 3600


def _gemini_model() -> DecisionModel:
    from returnguard.gemini import GeminiDecisionModel

    return GeminiDecisionModel.from_settings(load_settings())


def build_agent():
    from returnguard.agent import ReturnGuardAgent
    from returnguard.bloomreach import BloomreachClient
    from returnguard.config import load_bloomreach_settings, load_databricks_settings, load_shopify_settings
    from returnguard.lakehouse import LakehouseStore
    from returnguard.shopify import ShopifyClient

    return ReturnGuardAgent(
        shopify=ShopifyClient.from_settings(load_shopify_settings()),
        lakehouse=LakehouseStore.from_settings(load_databricks_settings()),
        bloomreach=BloomreachClient.from_settings(load_bloomreach_settings()),
        model=_gemini_model(),
    )


def _print_report(report) -> None:
    output = {
        "resolved_outcomes": list(report.resolved),
        "orders": [{"order": o.order_name, "status": o.status, "detail": o.detail} for o in report.orders],
    }
    print(json.dumps(output, indent=2), flush=True)


def _cmd_decide(args: argparse.Namespace, model: DecisionModel | None) -> int:
    context = ReturnRiskContext.model_validate_json(args.context_file.read_text(encoding="utf-8"))
    result = decide(context, model or _gemini_model())
    output = {
        "decision": result.decision.model_dump(mode="json"),
        "policy_adjustments": list(result.adjustments),
    }
    print(json.dumps(output, indent=2))
    return 0


def _cmd_run(agent_factory: Callable) -> int:
    _print_report(agent_factory().run_once())
    return 0


def _cmd_watch(args: argparse.Namespace, agent_factory: Callable, sleep: Callable[[float], None]) -> int:
    from returnguard.agent import AGENT_ERRORS

    agent = agent_factory()
    cycle = 0
    while True:
        try:
            _print_report(agent.run_once())
        except AGENT_ERRORS as exc:
            print(f"returnguard: cycle {cycle + 1} failed, will retry next cycle: {exc}", file=sys.stderr, flush=True)
        cycle += 1
        if args.cycles and cycle >= args.cycles:
            return 0
        sleep(args.interval)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="returnguard", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    decide_cmd = sub.add_parser("decide", help="One decision for a saved context file")
    decide_cmd.add_argument("context_file", type=Path)
    sub.add_parser("run", help="One full agent cycle")
    watch_cmd = sub.add_parser("watch", help="Run on a schedule")
    watch_cmd.add_argument("--interval", type=float, default=DEFAULT_WATCH_INTERVAL_SECONDS, help="Seconds between cycles")
    watch_cmd.add_argument("--cycles", type=int, default=0, help="Stop after N cycles (0 = run forever)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    model: DecisionModel | None = None,
    agent_factory: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    from returnguard.agent import AGENT_ERRORS

    args = _parser().parse_args(argv)
    factory = agent_factory or build_agent
    try:
        if args.command == "decide":
            return _cmd_decide(args, model)
        if args.command == "run":
            return _cmd_run(factory)
        return _cmd_watch(args, factory, sleep)
    except (OSError, ConfigError, *AGENT_ERRORS) as exc:
        print(f"returnguard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
