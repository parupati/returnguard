"""Turns raw Bloomreach events into the post-purchase engagement signal Gemini reasons over."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from returnguard.context import PostPurchaseEngagement
from returnguard.enums import EngagementTrend

ENGAGEMENT_EVENT_TYPES = ("campaign", "page_visit", "session_start")

RETURN_PAGE_MARKERS = ("return", "refund", "exchange")
ORDER_PAGE_MARKERS = ("/account/orders", "order-status", "/orders/")
TRACKING_MARKERS = ("track",)

TREND_WINDOW = timedelta(days=30)
DECLINE_RATIO = 0.7
RISE_RATIO = 1.3

Event = Mapping[str, Any]


def summarize_engagement(events: Sequence[Event], order_placed_at: datetime, now: datetime) -> PostPurchaseEngagement:
    since_order = [e for e in events if _at(e) >= order_placed_at]
    email_events = [e for e in since_order if _is_email(e)]
    page_urls = [_url(e) for e in since_order if e.get("type") == "page_visit"]

    return PostPurchaseEngagement(
        opened_confirmation_email=any(_status(e) in ("opened", "clicked") for e in email_events),
        clicked_tracking_link=any(
            _status(e) == "clicked" and _has(_url(e), TRACKING_MARKERS) for e in email_events
        )
        or any(_has(url, TRACKING_MARKERS) for url in page_urls),
        viewed_order_status_page=any(_has(url, ORDER_PAGE_MARKERS) for url in page_urls),
        visited_return_policy_page=any(_has(url, RETURN_PAGE_MARKERS) for url in page_urls),
        sessions_since_order=sum(1 for e in since_order if e.get("type") == "session_start"),
        email_engagement_trend=_email_trend(events, now),
    )


def _email_trend(events: Sequence[Event], now: datetime) -> EngagementTrend:
    engaged = [e for e in events if _is_email(e) and _status(e) in ("opened", "clicked")]
    recent = sum(1 for e in engaged if now - TREND_WINDOW <= _at(e) < now)
    previous = sum(1 for e in engaged if now - 2 * TREND_WINDOW <= _at(e) < now - TREND_WINDOW)
    if previous == 0:
        return EngagementTrend.RISING if recent > 0 else EngagementTrend.STABLE
    ratio = recent / previous
    if ratio < DECLINE_RATIO:
        return EngagementTrend.DECLINING
    if ratio > RISE_RATIO:
        return EngagementTrend.RISING
    return EngagementTrend.STABLE


def _at(event: Event) -> datetime:
    return datetime.fromtimestamp(float(event.get("timestamp", 0)), tz=timezone.utc)


def _props(event: Event) -> Mapping[str, Any]:
    return event.get("properties") or {}


def _is_email(event: Event) -> bool:
    return event.get("type") == "campaign" and _props(event).get("action_type") == "email"


def _status(event: Event) -> str:
    return str(_props(event).get("status", "")).lower()


def _url(event: Event) -> str:
    props = _props(event)
    return str(props.get("location") or props.get("url") or props.get("path") or "").lower()


def _has(url: str, markers: Sequence[str]) -> bool:
    return any(marker in url for marker in markers)
