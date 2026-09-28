import json
from datetime import datetime, timezone

import httpx
import pytest

from returnguard.config import ConfigError, ShopifySettings, load_shopify_settings
from returnguard.shopify import ShopifyClient, ShopifyError

SETTINGS = ShopifySettings("frontier.myshopify.com", "cid", "csecret", "2026-10")

ORDER_NODE = {
    "id": "gid://shopify/Order/1",
    "name": "#1001",
    "processedAt": "2026-09-24T10:00:00Z",
    "email": "ava@example.test",
    "displayFulfillmentStatus": "FULFILLED",
    "returnStatus": "NO_RETURN",
    "currencyCode": "USD",
    "totalPriceSet": {"shopMoney": {"amount": "59.00"}},
    "customer": {"id": "gid://shopify/Customer/9"},
    "lineItems": {
        "nodes": [
            {
                "sku": "PROD-004",
                "title": "Summit Skincare 04",
                "quantity": 1,
                "originalUnitPriceSet": {"shopMoney": {"amount": "59.00"}},
                "product": None,
            }
        ]
    },
}


class Recorder:
    def __init__(self, graphql_responses):
        self.graphql_responses = list(graphql_responses)
        self.token_requests = 0
        self.graphql_bodies = []

    def __call__(self, request):
        if request.url.path == "/admin/oauth/access_token":
            self.token_requests += 1
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": f"tok-{self.token_requests}", "expires_in": 86399})
        assert request.headers["X-Shopify-Access-Token"].startswith("tok-")
        self.graphql_bodies.append(json.loads(request.content))
        return self.graphql_responses.pop(0)


def _client(recorder, clock=lambda: 0.0):
    http = httpx.Client(base_url="https://frontier.myshopify.com", transport=httpx.MockTransport(recorder))
    return ShopifyClient(http, SETTINGS, clock=clock)


def test_recent_orders_parses_nodes_and_filters_by_date():
    recorder = Recorder([httpx.Response(200, json={"data": {"orders": {"nodes": [ORDER_NODE]}}})])
    orders = _client(recorder).recent_orders(datetime(2026, 9, 1, tzinfo=timezone.utc))

    order = orders[0]
    assert order.name == "#1001"
    assert order.delivered is True
    assert order.return_started is False
    assert order.customer_email == "ava@example.test"
    assert order.line_items[0].sku == "PROD-004"
    assert order.line_items[0].category == "uncategorized"
    assert order.processed_at == datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
    assert recorder.graphql_bodies[0]["variables"] == {"query": "processed_at:>='2026-09-01'"}


def test_orders_by_id_skips_missing_nodes_and_flags_returns():
    returned = {**ORDER_NODE, "returnStatus": "RETURN_REQUESTED"}
    recorder = Recorder([httpx.Response(200, json={"data": {"nodes": [returned, None]}})])
    orders = _client(recorder).orders_by_id(["gid://shopify/Order/1", "gid://shopify/Order/2"])
    assert list(orders) == ["gid://shopify/Order/1"]
    assert orders["gid://shopify/Order/1"].return_started is True


def test_orders_by_id_with_no_ids_makes_no_request():
    recorder = Recorder([])
    assert _client(recorder).orders_by_id([]) == {}
    assert recorder.token_requests == 0


def test_token_is_cached_until_near_expiry():
    now = [0.0]
    responses = [httpx.Response(200, json={"data": {"orders": {"nodes": []}}}) for _ in range(3)]
    recorder = Recorder(responses)
    client = _client(recorder, clock=lambda: now[0])
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)

    client.recent_orders(since)
    client.recent_orders(since)
    assert recorder.token_requests == 1

    now[0] = 86399.0
    client.recent_orders(since)
    assert recorder.token_requests == 2


def test_create_keep_discount_scopes_code_to_customer():
    ok = {"data": {"discountCodeBasicCreate": {"codeDiscountNode": {"id": "gid://d/1"}, "userErrors": []}}}
    recorder = Recorder([httpx.Response(200, json=ok)])
    start = datetime(2026, 9, 28, tzinfo=timezone.utc)

    discount_id = _client(recorder).create_keep_discount("RG-1001", 10, "gid://shopify/Customer/9", start, start)

    sent = recorder.graphql_bodies[0]["variables"]["discount"]
    assert discount_id == "gid://d/1"
    assert sent["context"] == {"customers": {"add": ["gid://shopify/Customer/9"]}}
    assert sent["customerGets"]["value"] == {"percentage": 0.1}
    assert sent["usageLimit"] == 1


def test_discount_user_errors_raise():
    bad = {"data": {"discountCodeBasicCreate": {"codeDiscountNode": None, "userErrors": [{"message": "taken"}]}}}
    recorder = Recorder([httpx.Response(200, json=bad)])
    start = datetime(2026, 9, 28, tzinfo=timezone.utc)
    with pytest.raises(ShopifyError, match="taken"):
        _client(recorder).create_keep_discount("RG-1", 5, "gid://c/1", start, start)


def test_graphql_errors_and_http_errors_raise():
    recorder = Recorder([httpx.Response(200, json={"errors": [{"message": "Field 'x' doesn't exist"}]})])
    with pytest.raises(ShopifyError, match="doesn't exist"):
        _client(recorder).graphql("{ x }", {})

    recorder = Recorder([httpx.Response(502, text="Bad gateway")])
    with pytest.raises(ShopifyError, match="HTTP 502"):
        _client(recorder).graphql("{ shop { name } }", {})


def test_network_errors_are_wrapped():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    http = httpx.Client(base_url="https://frontier.myshopify.com", transport=httpx.MockTransport(handler))
    with pytest.raises(ShopifyError, match="offline"):
        ShopifyClient(http, SETTINGS).graphql("{ shop { name } }", {})


def test_shopify_settings_validation():
    env = {
        "SHOPIFY_STORE_DOMAIN": "https://frontier.myshopify.com/",
        "SHOPIFY_CLIENT_ID": "id",
        "SHOPIFY_CLIENT_SECRET": "secret",
        "SHOPIFY_API_VERSION": "2026-10",
    }
    assert load_shopify_settings(env).store_domain == "frontier.myshopify.com"
    with pytest.raises(ConfigError, match="myshopify.com"):
        load_shopify_settings({**env, "SHOPIFY_STORE_DOMAIN": "evil.example.com"})
    assert ShopifyClient.from_settings(SETTINGS)._settings.store_domain == "frontier.myshopify.com"
