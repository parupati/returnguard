"""The structured decision Gemini must return. Also sent to Gemini as the response JSON schema."""

from pydantic import BaseModel, ConfigDict, Field

from returnguard.enums import Channel, IncentiveType, InterventionType, RiskLevel


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Incentive(_Frozen):
    incentive_type: IncentiveType
    percent_of_item_price: float = Field(gt=0, le=100)
    justification: str


class Message(_Frozen):
    subject: str = Field(description="Email subject or push title. Ignored for SMS.")
    body: str
    cta_text: str


class InterventionDecision(_Frozen):
    risk_level: RiskLevel
    risk_score: float = Field(ge=0, le=1, description="Probability the item is returned without intervention.")
    key_signals: list[str] = Field(description="The specific facts from the context that drove this decision.")
    intervention_type: InterventionType
    channel: Channel
    target_sku: str | None = Field(default=None, description="Must be a SKU from the order.")
    incentive: Incentive | None = None
    message: Message | None = None
    rationale: str = Field(description="One to three sentences a marketer can audit.")
