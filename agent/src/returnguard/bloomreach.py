"""Bloomreach Engagement: engagement signals in, customer profile updates and intervention events out."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx

from returnguard.config import BloomreachSettings

INTERVENTION_EVENT = "returnguard_intervention"


class BloomreachError(RuntimeError):
    pass


class BloomreachClient:
    def __init__(self, http: httpx.Client, project_token: str, customer_id_type: str) -> None:
        self._http = http
        self._project = project_token
        self._id_type = customer_id_type

    @classmethod
    def from_settings(cls, settings: BloomreachSettings) -> "BloomreachClient":
        http = httpx.Client(
            base_url=settings.api_base_url,
            auth=(settings.api_key_id, settings.api_secret),
            timeout=30,
        )
        return cls(http, settings.project_token, settings.customer_id_type)

    def update_customer(self, customer_key: str, properties: Mapping[str, Any]) -> None:
        self._track(
            "customers",
            {"customer_ids": self._ids(customer_key), "properties": dict(properties)},
        )

    def track_event(
        self, customer_key: str, event_type: str, properties: Mapping[str, Any], timestamp: datetime
    ) -> None:
        self._track(
            "customers/events",
            {
                "customer_ids": self._ids(customer_key),
                "event_type": event_type,
                "timestamp": timestamp.timestamp(),
                "properties": dict(properties),
            },
        )

    def customer_events(self, customer_key: str, event_types: Sequence[str]) -> list[dict[str, Any]]:
        resp = self._post(
            f"/data/v2/projects/{self._project}/customers/events",
            {"customer_ids": self._ids(customer_key), "event_types": list(event_types)},
            allow_not_found=True,
        )
        if resp is None:
            return []
        return list(resp.json().get("data", []))

    def _ids(self, customer_key: str) -> dict[str, str]:
        return {self._id_type: customer_key}

    def _track(self, path: str, payload: dict[str, Any]) -> None:
        resp = self._post(f"/track/v2/projects/{self._project}/{path}", payload)
        body = resp.json()
        if not body.get("success", False):
            raise BloomreachError(f"Bloomreach rejected {path}: {body.get('errors')}")

    def _post(self, path: str, payload: dict[str, Any], allow_not_found: bool = False) -> httpx.Response | None:
        try:
            resp = self._http.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise BloomreachError(f"Bloomreach request to {path} failed: {exc}") from exc
        if allow_not_found and resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise BloomreachError(f"Bloomreach {path} returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp
