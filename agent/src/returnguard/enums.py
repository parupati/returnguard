from enum import StrEnum


class EngagementTrend(StrEnum):
    DECLINING = "declining"
    STABLE = "stable"
    RISING = "rising"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InterventionType(StrEnum):
    NONE = "none"
    FIT_GUIDANCE = "fit_guidance"
    USAGE_TIPS = "usage_tips"
    EXCHANGE_OFFER = "exchange_offer"
    PROACTIVE_SUPPORT = "proactive_support"
    KEEP_INCENTIVE = "keep_incentive"


class Channel(StrEnum):
    NONE = "none"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEB_LAYER = "web_layer"


class IncentiveType(StrEnum):
    STORE_CREDIT = "store_credit"
    NEXT_ORDER_DISCOUNT = "next_order_discount"
    LOYALTY_POINTS = "loyalty_points"
