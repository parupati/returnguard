"""Shopify Admin GraphQL: orders in, return outcomes in, keep-incentive discount codes out."""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from returnguard.config import ShopifySettings

TOKEN_REFRESH_MARGIN_SECONDS = 300
RETURN_STARTED_STATUSES = frozenset({"RETURN_REQUESTED", "IN_PROGRESS", "INSPECTION_COMPLETE", "RETURNED"})

ORDER_FIELDS = """
  id
  name
  processedAt
  email
  displayFulfillmentStatus
  returnStatus
  currencyCode
  totalPriceSet { shopMoney { amount } }
  customer { id }
  lineItems(first: 20) {
    nodes {
      sku
      title
      quantity
      originalUnitPriceSet { shopMoney { amount } }
      product { productType }
    }
  }
"""

RECENT_ORDERS_QUERY = f"""
query RecentOrders($query: String!) {{
  orders(first: 50, query: $query, sortKey: PROCESSED_AT, reverse: true) {{
    nodes {{ {ORDER_FIELDS} }}
  }}
}}
"""

ORDERS_BY_ID_QUERY = f"""
query OrdersById($ids: [ID!]!) {{
  nodes(ids: $ids) {{
    ... on Order {{ {ORDER_FIELDS} }}
  }}
}}
"""

DISCOUNT_CREATE_MUTATION = """
mutation KeepIncentive($discount: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $discount) {
    codeDiscountNode { id }
    userErrors { field message }
  }
}
"""


class ShopifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShopifyLineItem:
    sku: str
    title: str
    category: str
    quantity: int
    unit_price: float


@dataclass(frozen=True)
class ShopifyOrder:
    id: str
    name: str
    processed_at: datetime
    customer_email: str | None
    customer_id: str | None
    delivered: bool
    return_status: str
    currency: str
    total: float
    line_items: tuple[ShopifyLineItem, ...]

    @property
    def return_started(self) -> bool:
        return self.return_status in RETURN_STARTED_STATUSES


class ShopifyClient:
    def __init__(
        self,
        http: httpx.Client,
        settings: ShopifySettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._settings = settings
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    @classmethod
    def from_settings(cls, settings: ShopifySettings) -> "ShopifyClient":
        return cls(httpx.Client(base_url=f"https://{settings.store_domain}", timeout=30), settings)

    def recent_orders(self, since: datetime) -> list[ShopifyOrder]:
        data = self.graphql(RECENT_ORDERS_QUERY, {"query": f"processed_at:>='{since.date().isoformat()}'"})
        return [_parse_order(node) for node in data["orders"]["nodes"]]

    def orders_by_id(self, order_ids: Sequence[str]) -> dict[str, ShopifyOrder]:
        if not order_ids:
            return {}
        data = self.graphql(ORDERS_BY_ID_QUERY, {"ids": list(order_ids)})
        orders = [_parse_order(node) for node in data["nodes"] if node]
        return {order.id: order for order in orders}

    def create_keep_discount(
        self, code: str, percent: float, customer_id: str, starts_at: datetime, ends_at: datetime
    ) -> str:
        discount = {
            "title": f"ReturnGuard thank-you {code}",
            "code": code,
            "startsAt": starts_at.isoformat(),
            "endsAt": ends_at.isoformat(),
            "usageLimit": 1,
            "appliesOncePerCustomer": True,
            "context": {"customers": {"add": [customer_id]}},
            "customerGets": {"value": {"percentage": round(percent / 100, 4)}, "items": {"all": True}},
        }
        data = self.graphql(DISCOUNT_CREATE_MUTATION, {"discount": discount})
        result = data["discountCodeBasicCreate"]
        if result["userErrors"]:
            raise ShopifyError(f"Discount {code} rejected: {result['userErrors']}")
        return result["codeDiscountNode"]["id"]

    def graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        resp = self._request(
            f"/admin/api/{self._settings.api_version}/graphql.json",
            json={"query": query, "variables": dict(variables)},
            headers={"X-Shopify-Access-Token": self._access_token()},
        )
        body = resp.json()
        if body.get("errors"):
            raise ShopifyError(f"Shopify GraphQL errors: {body['errors']}")
        return body["data"]

    def _access_token(self) -> str:
        if self._token and self._clock() < self._token_expires_at:
            return self._token
        resp = self._request(
            "/admin/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
            },
        )
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = self._clock() + float(body.get("expires_in", 3600)) - TOKEN_REFRESH_MARGIN_SECONDS
        return self._token

    def _request(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._http.post(path, **kwargs)
        except httpx.HTTPError as exc:
            raise ShopifyError(f"Shopify request to {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ShopifyError(f"Shopify {path} returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp


def _parse_order(node: Mapping[str, Any]) -> ShopifyOrder:
    customer = node.get("customer") or {}
    return ShopifyOrder(
        id=node["id"],
        name=node["name"],
        processed_at=datetime.fromisoformat(node["processedAt"].replace("Z", "+00:00")),
        customer_email=node.get("email"),
        customer_id=customer.get("id"),
        delivered=node["displayFulfillmentStatus"] == "FULFILLED",
        return_status=node["returnStatus"],
        currency=node["currencyCode"],
        total=float(node["totalPriceSet"]["shopMoney"]["amount"]),
        line_items=tuple(
            ShopifyLineItem(
                sku=item.get("sku") or "",
                title=item["title"],
                category=((item.get("product") or {}).get("productType")) or "uncategorized",
                quantity=int(item["quantity"]),
                unit_price=float(item["originalUnitPriceSet"]["shopMoney"]["amount"]),
            )
            for item in node["lineItems"]["nodes"]
        ),
    )
