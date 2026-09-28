from typing import Any

from google import genai
from google.genai import errors, types

from returnguard.config import Settings
from returnguard.reasoning import ReasoningError


class GeminiDecisionModel:
    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "GeminiDecisionModel":
        return cls(genai.Client(api_key=settings.gemini_api_key), settings.gemini_model)

    def generate(self, *, system_instruction: str, prompt: str, response_schema: dict[str, Any]) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=response_schema,
                    temperature=0.2,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except errors.APIError as exc:
            raise ReasoningError(f"Gemini model {self._model} request failed: {exc}") from exc
        if not response.text:
            raise ReasoningError(f"Gemini model {self._model} returned an empty response.")
        return response.text
