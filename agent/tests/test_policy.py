import pytest

from conftest import make_decision
from returnguard.enums import Channel, InterventionType
from returnguard.policy import apply_policy, max_incentive_percent


@pytest.mark.parametrize(
    ("lifetime_value", "expected_cap"),
    [(0, 5.0), (199.99, 5.0), (200, 10.0), (999, 10.0), (1000, 15.0), (50_000, 15.0)],
)
def test_incentive_cap_tiers(lifetime_value, expected_cap):
    assert max_incentive_percent(lifetime_value) == expected_cap


def test_valid_decision_passes_unchanged(context):
    decision = make_decision()
    result = apply_policy(decision, context)
    assert result.decision == decision
    assert result.adjustments == ()


def test_clean_no_action_passes_unchanged(context):
    decision = make_decision(intervention_type="none", channel="none", target_sku=None, message=None)
    result = apply_policy(decision, context)
    assert result.decision == decision
    assert result.adjustments == ()


def test_no_action_with_leftover_outreach_is_cleared(context):
    result = apply_policy(make_decision(intervention_type="none"), context)
    assert result.decision.channel is Channel.NONE
    assert result.decision.message is None
    assert result.decision.target_sku is None
    assert len(result.adjustments) == 1


def test_closed_return_window_suppresses_outreach(context):
    closed = context.model_copy(update={"order": context.order.model_copy(update={"days_left_in_return_window": 0})})
    result = apply_policy(make_decision(), closed)
    assert result.decision.intervention_type is InterventionType.NONE
    assert "window" in result.adjustments[0]


def test_no_marketing_consent_suppresses_outreach(context):
    opted_out = context.model_copy(update={"customer": context.customer.model_copy(update={"marketing_opt_in": False})})
    result = apply_policy(make_decision(), opted_out)
    assert result.decision.intervention_type is InterventionType.NONE
    assert "opted in" in result.adjustments[0]


def test_missing_message_suppresses_outreach(context):
    result = apply_policy(make_decision(message=None), context)
    assert result.decision.intervention_type is InterventionType.NONE


def test_missing_channel_suppresses_outreach(context):
    result = apply_policy(make_decision(channel="none"), context)
    assert result.decision.intervention_type is InterventionType.NONE


def test_sku_not_in_order_suppresses_outreach(context):
    result = apply_policy(make_decision(target_sku="MADE-UP-SKU"), context)
    assert result.decision.intervention_type is InterventionType.NONE
    assert "MADE-UP-SKU" in result.adjustments[0]


def test_incentive_removed_when_not_keep_incentive(context):
    incentive = {"incentive_type": "store_credit", "percent_of_item_price": 5, "justification": "goodwill"}
    result = apply_policy(make_decision(incentive=incentive), context)
    assert result.decision.incentive is None
    assert result.decision.intervention_type is InterventionType.EXCHANGE_OFFER


def test_incentive_within_cap_is_kept(context):
    incentive = {"incentive_type": "store_credit", "percent_of_item_price": 12, "justification": "high LTV"}
    decision = make_decision(intervention_type="keep_incentive", incentive=incentive)
    result = apply_policy(decision, context)
    assert result.decision == decision


def test_incentive_above_cap_is_capped_without_mutating_input(context):
    incentive = {"incentive_type": "store_credit", "percent_of_item_price": 40, "justification": "too generous"}
    decision = make_decision(intervention_type="keep_incentive", incentive=incentive)
    result = apply_policy(decision, context)
    assert result.decision.incentive.percent_of_item_price == 15.0
    assert decision.incentive.percent_of_item_price == 40
    assert "40%" in result.adjustments[0]
