from types import SimpleNamespace

import pytest
from google.genai import errors

from conftest import FakeModel, make_decision
from returnguard.config import Settings
from returnguard.enums import InterventionType
from returnguard.gemini import GeminiDecisionModel
from returnguard.reasoning import SYSTEM_INSTRUCTION, ReasoningError, build_prompt, decide


def test_prompt_includes_order_and_customer_cap(context):
    prompt = build_prompt(context)
    assert "Maximum incentive for this customer: 15% of the item price." in prompt
    assert '"order_id": "1042"' in prompt
    assert "BLZ-MER-NVY-40" in prompt


def test_decide_sends_schema_and_applies_policy(context):
    model = FakeModel(make_decision(target_sku="NOT-IN-ORDER").model_dump_json())
    result = decide(context, model)

    call = model.calls[0]
    assert call["system_instruction"] == SYSTEM_INSTRUCTION
    assert "intervention_type" in call["response_schema"]["properties"]
    assert result.decision.intervention_type is InterventionType.NONE


def test_decide_rejects_malformed_output(context):
    with pytest.raises(ReasoningError, match="1042"):
        decide(context, FakeModel('{"risk_level": "catastrophic"}'))


class _FakeModels:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.kwargs: dict = {}

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text=self.text)


def test_gemini_model_requests_json_with_schema():
    models = _FakeModels('{"ok": true}')
    gemini = GeminiDecisionModel(SimpleNamespace(models=models), "gemini-test")

    text = gemini.generate(system_instruction="sys", prompt="p", response_schema={"type": "object"})

    assert text == '{"ok": true}'
    assert models.kwargs["model"] == "gemini-test"
    config = models.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert config.system_instruction == "sys"


def test_gemini_model_raises_on_empty_response():
    gemini = GeminiDecisionModel(SimpleNamespace(models=_FakeModels(None)), "gemini-test")
    with pytest.raises(ReasoningError, match="empty"):
        gemini.generate(system_instruction="s", prompt="p", response_schema={})


def test_gemini_model_wraps_api_errors():
    class _FailingModels:
        def generate_content(self, **kwargs):
            raise errors.ClientError(404, {"error": {"code": 404, "message": "model gone", "status": "NOT_FOUND"}})

    gemini = GeminiDecisionModel(SimpleNamespace(models=_FailingModels()), "gemini-old")
    with pytest.raises(ReasoningError, match="gemini-old"):
        gemini.generate(system_instruction="s", prompt="p", response_schema={})


def test_gemini_model_builds_from_settings():
    gemini = GeminiDecisionModel.from_settings(Settings(gemini_api_key="test-key", gemini_model="gemini-x"))
    assert gemini._model == "gemini-x"
