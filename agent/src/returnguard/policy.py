"""Guardrails enforced in code after Gemini decides, so safety never depends on the model obeying the prompt."""

from dataclasses import dataclass

from returnguard.context import ReturnRiskContext
from returnguard.decision import InterventionDecision
from returnguard.enums import Channel, InterventionType

# (minimum lifetime value, max incentive as % of item price), highest tier first.
INCENTIVE_CAP_TIERS: tuple[tuple[float, float], ...] = (
    (1000.0, 15.0),
    (200.0, 10.0),
    (0.0, 5.0),
)


@dataclass(frozen=True)
class PolicyResult:
    decision: InterventionDecision
    adjustments: tuple[str, ...]


def max_incentive_percent(lifetime_value: float) -> float:
    return next(cap for threshold, cap in INCENTIVE_CAP_TIERS if lifetime_value >= threshold)


def apply_policy(decision: InterventionDecision, context: ReturnRiskContext) -> PolicyResult:
    if decision.intervention_type is InterventionType.NONE:
        return _normalize_no_action(decision)
    block_reason = _block_reason(decision, context)
    if block_reason is not None:
        return PolicyResult(_as_no_action(decision), (block_reason,))
    return _enforce_incentive(decision, context)


def _as_no_action(decision: InterventionDecision) -> InterventionDecision:
    return decision.model_copy(
        update={
            "intervention_type": InterventionType.NONE,
            "channel": Channel.NONE,
            "target_sku": None,
            "incentive": None,
            "message": None,
        }
    )


def _normalize_no_action(decision: InterventionDecision) -> PolicyResult:
    normalized = _as_no_action(decision)
    if normalized == decision:
        return PolicyResult(decision, ())
    return PolicyResult(normalized, ("Cleared outreach fields on a no-action decision.",))


def _block_reason(decision: InterventionDecision, context: ReturnRiskContext) -> str | None:
    if not context.customer.marketing_opt_in:
        return "Customer has not opted in to marketing; outreach suppressed."
    if context.order.days_left_in_return_window <= 0:
        return "Return window is closed; outreach suppressed."
    if decision.channel is Channel.NONE or decision.message is None:
        return "Intervention had no channel or message; outreach suppressed."
    order_skus = {item.sku for item in context.order.line_items}
    if decision.target_sku is not None and decision.target_sku not in order_skus:
        return (
            f"target_sku {decision.target_sku!r} is not in order "
            f"{context.order.order_id}; outreach suppressed."
        )
    return None


def _enforce_incentive(decision: InterventionDecision, context: ReturnRiskContext) -> PolicyResult:
    incentive = decision.incentive
    if incentive is None:
        return PolicyResult(decision, ())
    if decision.intervention_type is not InterventionType.KEEP_INCENTIVE:
        return PolicyResult(
            decision.model_copy(update={"incentive": None}),
            ("Removed incentive: only keep_incentive decisions may carry one.",),
        )
    cap = max_incentive_percent(context.customer.lifetime_value)
    if incentive.percent_of_item_price <= cap:
        return PolicyResult(decision, ())
    capped = incentive.model_copy(update={"percent_of_item_price": cap})
    return PolicyResult(
        decision.model_copy(update={"incentive": capped}),
        (f"Capped incentive from {incentive.percent_of_item_price:g}% to {cap:g}% for the customer's value tier.",),
    )
