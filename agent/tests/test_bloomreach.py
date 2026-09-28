import json
from datetime import datetime, timezone

import httpx
import pytest

from returnguard.bloomreach import BloomreachClient, BloomreachError
from returnguard.config import BloomreachSettings


def _client(handler):
    http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    return BloomreachClient(http, "proj", "email_id")


def test_update_customer_posts_properties_with_configured_id():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    _client(handler).update_customer("ava@example.test", {"returnguard_risk_score": 0.8})

    assert seen["path"] == "/track/v2/projects/proj/customers"
    assert seen["body"] == {
        "customer_ids": {"email_id": "ava@example.test"},
        "properties": {"returnguard_risk_score": 0.8},
    }


def test_track_event_sends_epoch_timestamp():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    at = datetime(2026, 9, 28, tzinfo=timezone.utc)
    _client(handler).track_event("ava@example.test", "returnguard_intervention", {"channel": "sms"}, at)

    assert seen["body"]["event_type"] == "returnguard_intervention"
    assert seen["body"]["timestamp"] == at.timestamp()
    assert seen["body"]["properties"] == {"channel": "sms"}


def test_tracking_failure_flag_raises():
    client = _client(lambda request: httpx.Response(200, json={"success": False, "errors": ["bad"]}))
    with pytest.raises(BloomreachError, match="bad"):
        client.update_customer("x@example.test", {})


def test_http_error_status_raises_with_detail():
    client = _client(lambda request: httpx.Response(403, text="No permission"))
    with pytest.raises(BloomreachError, match="HTTP 403: No permission"):
        client.update_customer("x@example.test", {})


def test_network_error_is_wrapped():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(BloomreachError, match="offline"):
        _client(handler).customer_events("x@example.test", ["page_visit"])


def test_customer_events_returns_data_and_empty_for_unknown_customer():
    events = [{"type": "page_visit", "timestamp": 1, "properties": {}}]
    found = _client(lambda request: httpx.Response(200, json={"success": True, "data": events}))
    missing = _client(lambda request: httpx.Response(404, json={"errors": {"_global": ["Customer does not exist"]}}))

    assert found.customer_events("x@example.test", ["page_visit"]) == events
    assert missing.customer_events("x@example.test", ["page_visit"]) == []


def test_from_settings_configures_basic_auth():
    settings = BloomreachSettings("https://api.test", "proj", "kid", "secret", "email_id")
    client = BloomreachClient.from_settings(settings)
    assert client._http.auth is not None
    assert str(client._http.base_url) == "https://api.test"
