from typing import Any, Protocol

from pydantic import ValidationError

from returnguard.context import ReturnRiskContext
from returnguard.decision import InterventionDecision
from returnguard.policy import PolicyResult, apply_policy, max_incentive_percent

SYSTEM_INSTRUCTION = """\
You are ReturnGuard, the decision layer of an autonomous post-purchase agent for an online retailer.

You receive the context for one order, assembled at runtime from three systems:
- Shopify: the order and its line items.
- Databricks Lakehouse: return-rate history per SKU and per customer, lifetime value, churn risk,
  and the outcomes of earlier interventions for this customer.
- Bloomreach: the customer's engagement since the order was placed.

Decide whether this order is likely to be returned and, if so, choose the single most useful intervention.

How to reason:
1. No single signal is enough. A high SKU return rate alone is noise. Weigh it together with the customer's
   own return history, their engagement since purchase, and the time left in the return window.
   A visit to the return policy page is the strongest single signal: the customer is thinking about a refund.
   A visit to the exchange page means something different: they like the product but want another size or
   variant, so prefer exchange_offer.
2. Prefer helping over paying, and match the help to the likely reason for a return. Use the SKU's
   top_return_reason when present. When it is missing, use the category's typical return driver:
{category_drivers}
   Choose keep_incentive only for high-value customers when help alone is unlikely to work.
3. Learn from history. If an intervention type already failed to prevent a return for this customer, do not
   choose it again.
4. Choose the channel from engagement. If the email trend is declining or the confirmation email went unopened,
   do not use email. Otherwise prefer the customer's preferred_channel ("app" means push, "web" means web_layer).
   A recent support case is a strong sign the customer is unhappy: prefer proactive_support.
5. If risk is low, return intervention_type "none", channel "none", and no message. Not contacting the customer
   is a valid and often correct decision.
6. Write as the brand: warm, and specific to the product they bought. Never mention "return risk", never guilt
   the customer, and never discourage a legitimate return. Keep SMS bodies under 300 characters.
   Never write URLs or links. The delivery system attaches the real link to cta_text.
7. target_sku must be one of the SKUs in the order.
8. If you propose an incentive, stay within the maximum given for this customer.
9. key_signals lists the specific facts that drove the decision. rationale is one to three sentences a marketer
   can audit.
"""

# Merchant playbook: what usually drives returns in each category, and the help that addresses it.
CATEGORY_RETURN_DRIVERS: dict[str, str] = {
    "Apparel": "fit or size is off -> fit_guidance, or exchange_offer for another size",
    "Sports": "fit, size or comfort -> fit_guidance, or exchange_offer for another size",
    "Beauty": "results take time, or the shade or skin reaction is wrong -> usage_tips (routine, patch test, shade help)",
    "Electronics": "setup or compatibility trouble -> usage_tips (setup guide), or proactive_support",
    "Home": "looks or fits differently in the room than in the photos -> proactive_support, or exchange_offer",
}

SYSTEM_INSTRUCTION = SYSTEM_INSTRUCTION.format(
    category_drivers="\n".join(f"   - {category}: {driver}" for category, driver in CATEGORY_RETURN_DRIVERS.items())
)


class ReasoningError(RuntimeError):
    pass


class DecisionModel(Protocol):
    def generate(self, *, system_instruction: str, prompt: str, response_schema: dict[str, Any]) -> str: ...


def build_prompt(context: ReturnRiskContext) -> str:
    cap = max_incentive_percent(context.customer.lifetime_value)
    return (
        f"Maximum incentive for this customer: {cap:g}% of the item price.\n\n"
        f"Order context (JSON):\n{context.model_dump_json(indent=2)}"
    )


def decide(context: ReturnRiskContext, model: DecisionModel) -> PolicyResult:
    raw = model.generate(
        system_instruction=SYSTEM_INSTRUCTION,
        prompt=build_prompt(context),
        response_schema=InterventionDecision.model_json_schema(),
    )
    try:
        decision = InterventionDecision.model_validate_json(raw)
    except ValidationError as exc:
        raise ReasoningError(
            f"Model output for order {context.order.order_id} did not match the decision schema: {exc}"
        ) from exc
    return apply_policy(decision, context)
