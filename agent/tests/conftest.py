import json
from pathlib import Path
from typing import Any

import pytest

from returnguard.context import ReturnRiskContext
from returnguard.decision import InterventionDecision

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_context.json"


@pytest.fixture
def context_path() -> Path:
    return FIXTURE_PATH


@pytest.fixture
def context() -> ReturnRiskContext:
    return ReturnRiskContext.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def context_data() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def make_decision(**overrides: Any) -> InterventionDecision:
    base: dict[str, Any] = {
        "risk_level": "high",
        "risk_score": 0.72,
        "key_signals": ["visited return policy page", "SKU runs small"],
        "intervention_type": "exchange_offer",
        "channel": "sms",
        "target_sku": "BLZ-MER-NVY-40",
        "incentive": None,
        "message": {
            "subject": "",
            "body": "Loving the blazer? If 40R feels snug, we'll swap it for 42R free.",
            "cta_text": "Swap my size",
        },
        "rationale": "Fit-driven return risk; offer an exchange before a refund.",
    }
    return InterventionDecision.model_validate({**base, **overrides})


class FakeModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, system_instruction: str, prompt: str, response_schema: dict[str, Any]) -> str:
        self.calls.append(
            {"system_instruction": system_instruction, "prompt": prompt, "response_schema": response_schema}
        )
        return self.response
