from datetime import datetime, timedelta, timezone

from returnguard.engagement import summarize_engagement
from returnguard.enums import EngagementTrend

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
ORDER_AT = NOW - timedelta(days=4)


def _event(kind, days_ago, **props):
    return {"type": kind, "timestamp": (NOW - timedelta(days=days_ago)).timestamp(), "properties": props}


def _email(days_ago, status, url=""):
    return _event("campaign", days_ago, action_type="email", status=status, url=url)


def test_no_events_is_quiet_and_stable():
    summary = summarize_engagement([], ORDER_AT, NOW)
    assert summary.opened_confirmation_email is False
    assert summary.visited_return_policy_page is False
    assert summary.sessions_since_order == 0
    assert summary.email_engagement_trend is EngagementTrend.STABLE


def test_post_order_page_visits_are_classified():
    events = [
        _event("page_visit", 2, location="https://shop.test/pages/returns-policy"),
        _event("page_visit", 1, location="https://shop.test/account/orders/1042"),
        _event("page_visit", 1, location="https://shop.test/apps/track-order"),
        _event("session_start", 2),
        _event("session_start", 1),
        _event("page_visit", 10, location="https://shop.test/pages/exchange"),
    ]
    summary = summarize_engagement(events, ORDER_AT, NOW)
    assert summary.visited_return_policy_page is True
    assert summary.viewed_order_status_page is True
    assert summary.clicked_tracking_link is True
    assert summary.sessions_since_order == 2


def test_only_events_after_the_order_count():
    events = [_event("page_visit", 10, location="https://shop.test/pages/returns"), _email(10, "opened")]
    summary = summarize_engagement(events, ORDER_AT, NOW)
    assert summary.visited_return_policy_page is False
    assert summary.opened_confirmation_email is False


def test_email_open_and_tracking_click_after_order():
    events = [_email(3, "opened"), _email(2, "clicked", url="https://carrier.test/track/123")]
    summary = summarize_engagement(events, ORDER_AT, NOW)
    assert summary.opened_confirmation_email is True
    assert summary.clicked_tracking_link is True


def test_declining_email_trend():
    events = [_email(40, "opened"), _email(45, "clicked"), _email(50, "opened"), _email(5, "opened")]
    assert summarize_engagement(events, ORDER_AT, NOW).email_engagement_trend is EngagementTrend.DECLINING


def test_rising_and_stable_email_trends():
    rising = [_email(40, "opened"), _email(5, "opened"), _email(6, "clicked")]
    stable = [_email(40, "opened"), _email(5, "opened")]
    first_ever = [_email(5, "opened")]
    assert summarize_engagement(rising, ORDER_AT, NOW).email_engagement_trend is EngagementTrend.RISING
    assert summarize_engagement(stable, ORDER_AT, NOW).email_engagement_trend is EngagementTrend.STABLE
    assert summarize_engagement(first_ever, ORDER_AT, NOW).email_engagement_trend is EngagementTrend.RISING


def test_non_email_campaigns_are_ignored():
    events = [_event("campaign", 2, action_type="sms", status="clicked")]
    assert summarize_engagement(events, ORDER_AT, NOW).opened_confirmation_email is False
