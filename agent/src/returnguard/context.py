"""The context object the agent assembles at runtime before asking Gemini to decide.

Each section is annotated with the system it comes from, which is also the
system-touch table in the submission.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from returnguard.enums import EngagementTrend, InterventionType


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CustomerProfile(_Frozen):
    """Databricks Lakehouse features. Deliberately excludes email and name: no PII is sent to Gemini."""

    customer_id: str = Field(min_length=1)
    loyalty_tier: str | None = None
    preferred_channel: str | None = None
    marketing_opt_in: bool
    lifetime_value: float = Field(ge=0)
    lifetime_orders: int = Field(ge=0)
    historical_return_rate: float = Field(ge=0, le=1)
    churn_risk: float | None = Field(default=None, ge=0, le=1)
    support_cases_30d: int = Field(default=0, ge=0)


class LineItem(_Frozen):
    """Shopify line item enriched with Databricks per-SKU return history."""

    sku: str = Field(min_length=1)
    product_title: str
    category: str
    unit_price: float = Field(ge=0)
    quantity: int = Field(ge=1)
    sku_return_rate: float = Field(ge=0, le=1)
    top_return_reason: str | None = None


class OrderSnapshot(_Frozen):
    """Shopify order."""

    order_id: str = Field(min_length=1)
    placed_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    total_value: float = Field(ge=0)
    delivered: bool
    days_since_order: int = Field(ge=0)
    days_left_in_return_window: int
    line_items: tuple[LineItem, ...] = Field(min_length=1)


class PostPurchaseEngagement(_Frozen):
    """Bloomreach engagement events since the order was placed."""

    opened_confirmation_email: bool
    clicked_tracking_link: bool
    viewed_order_status_page: bool
    visited_return_policy_page: bool
    sessions_since_order: int = Field(ge=0)
    email_engagement_trend: EngagementTrend


class PriorIntervention(_Frozen):
    """Outcome log written back to Databricks after each intervention (the learning loop)."""

    order_id: str
    intervention_type: InterventionType
    item_returned: bool


class ReturnRiskContext(_Frozen):
    customer: CustomerProfile
    order: OrderSnapshot
    engagement: PostPurchaseEngagement
    prior_interventions: tuple[PriorIntervention, ...] = ()
