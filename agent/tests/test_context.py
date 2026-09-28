import pytest
from pydantic import ValidationError

from returnguard.context import ReturnRiskContext
from returnguard.enums import EngagementTrend, InterventionType


def test_sample_fixture_parses(context):
    assert context.order.order_id == "1042"
    assert len(context.order.line_items) == 2
    assert context.engagement.email_engagement_trend is EngagementTrend.DECLINING
    assert context.prior_interventions[0].intervention_type is InterventionType.USAGE_TIPS


def test_context_is_immutable(context):
    with pytest.raises(ValidationError):
        context.customer.lifetime_value = 0


def test_rejects_return_rate_above_one(context_data):
    context_data["customer"]["historical_return_rate"] = 1.2
    with pytest.raises(ValidationError):
        ReturnRiskContext.model_validate(context_data)


def test_rejects_order_without_line_items(context_data):
    context_data["order"]["line_items"] = []
    with pytest.raises(ValidationError):
        ReturnRiskContext.model_validate(context_data)


def test_rejects_unknown_fields(context_data):
    context_data["customer"]["favourite_colour"] = "navy"
    with pytest.raises(ValidationError):
        ReturnRiskContext.model_validate(context_data)
