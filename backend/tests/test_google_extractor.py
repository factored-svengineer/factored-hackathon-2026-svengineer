"""Google AI Studio extractor integration tests (provider calls are mocked)."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest
from app.graph import google_extractor
from app.graph.extract import ExtractedEntities
from app.graph.nodes import understand
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_google_extractor_returns_structured_entities(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    extracted = google_extractor.EntityExtractionResponse(
        amount=42,
        currency="USD",
        transaction_date="2026-02-10",
        merchant_name="Google Play",
        transaction_id="394-#53D",
        language="en",
    )

    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "test-model"
            assert "Amount of: 42$ USD" in kwargs["contents"]
            assert "ID:394-#53D" in kwargs["contents"]
            assert "explicitly requested response language" in kwargs["contents"]
            assert "Requested language override: en." in kwargs["contents"]
            assert kwargs["config"].response_mime_type == "application/json"
            assert "additionalProperties" not in (
                kwargs["config"].response_schema.model_json_schema()
            )
            properties = kwargs["config"].response_schema.model_json_schema()["properties"]
            assert "language" in properties
            assert "language_hint" not in properties
            return type("Response", (), {"parsed": extracted, "text": None})()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeClient:
        def __init__(self, *, api_key):
            assert api_key == "test-api-key"
            self.models = FakeModels()

        def close(self):
            pass

    google_module = ModuleType("google")
    google_module.__path__ = []
    genai_module = ModuleType("google.genai")
    genai_module.Client = FakeClient
    types_module = ModuleType("google.genai.types")
    types_module.GenerateContentConfig = FakeConfig
    genai_module.types = types_module
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    result = google_extractor.extract_entities_with_google(
        "I had a miss transaction with an Amount of: 42$ USD, "
        "Date: 02/10/2026, Merchant or beneficiary: Google Play, ID:394-#53D",
        language_hint="en",
    )

    assert result.amount == 42
    assert result.currency == "USD"
    assert result.transaction_date is None
    assert result.merchant_name == "Google Play"
    assert result.transaction_id == "394-#53D"
    assert result.missing == []


def test_google_extractor_retries_transient_provider_errors(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

    class TemporaryProviderError(Exception):
        code = 503
        status = "UNAVAILABLE"

    extracted = google_extractor.EntityExtractionResponse(
        amount=42,
        currency="USD",
        transaction_date="2026-06-01",
        merchant_name="Google Play",
        transaction_id=None,
        language="en",
    )

    class FakeModels:
        attempts = 0

        def generate_content(self, *, model, contents, config):
            assert model
            assert contents
            assert config.response_mime_type == "application/json"
            self.attempts += 1
            if self.attempts < 3:
                raise TemporaryProviderError()
            return type("Response", (), {"parsed": extracted, "text": None})()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    models = FakeModels()

    class FakeClient:
        def __init__(self, *, api_key):
            assert api_key == "test-api-key"
            self.models = models

        def close(self):
            pass

    google_module = ModuleType("google")
    google_module.__path__ = []
    genai_module = ModuleType("google.genai")
    genai_module.Client = FakeClient
    types_module = ModuleType("google.genai.types")
    types_module.GenerateContentConfig = FakeConfig
    genai_module.types = types_module
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)
    sleeps = []
    monkeypatch.setattr(google_extractor.time, "sleep", sleeps.append)

    result = google_extractor.extract_entities_with_google(
        "USD 42.00 at Google Play on 2026-06-01",
        language_hint="en",
    )

    assert result.amount == 42
    assert models.attempts == 3
    assert sleeps == [0.5, 1.0]


def test_understand_uses_google_extractor_result(monkeypatch):
    expected = ExtractedEntities(
        amount=42,
        currency="USD",
        transaction_date="2026-10-02",
        merchant_name="Google Play",
        transaction_id="394-#53D",
    )
    extraction_calls = []
    lookup_calls = []

    def fake_extractor(text, language_hint=None):
        extraction_calls.append((text, language_hint))
        return expected

    def fake_transaction_lookup(transaction_id, transaction_date=None):
        lookup_calls.append((transaction_id, transaction_date))

    monkeypatch.setattr(google_extractor, "extract_entities_with_google", fake_extractor)
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        fake_transaction_lookup,
    )
    state = understand(
        {
            "text": "I dispute a 42 USD charge at Google Play, ID 394-#53D",
            "language": "en",
        }
    )

    assert extraction_calls == [
        ("I dispute a 42 USD charge at Google Play, ID 394-#53D", "en")
    ]
    assert lookup_calls == [("394-#53D", "2026-10-02")]
    assert state["amount"] == 42
    assert state["currency"] == "USD"
    assert state["transaction_date"] == "2026-10-02"
    assert state["merchant_name"] == "Google Play"
    assert state["transaction_id"] == "394-#53D"


def test_triage_endpoint_returns_503_for_placeholder_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "PASTE_YOUR_GOOGLE_AI_STUDIO_API_KEY_HERE")

    response = client.post(
        "/disputes/triage",
        json={"text": "I dispute a charge", "language": "en"},
    )

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_triage_endpoint_returns_429_for_google_quota_exhaustion(monkeypatch):
    def raise_quota_error(_text, language_hint=None):
        raise google_extractor.GoogleAIStudioQuotaError(
            "Google AI Studio request quota has been reached."
        )

    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        raise_quota_error,
    )

    response = client.post(
        "/disputes/triage",
        json={"text": "I dispute an unrecognized charge.", "language": "en"},
    )

    assert response.status_code == 429
    assert "request quota has been reached" in response.json()["detail"]


@pytest.mark.parametrize(
    "api_key",
    ["", "PASTE_YOUR_GOOGLE_AI_STUDIO_API_KEY_HERE"],
)
def test_placeholder_api_key_is_rejected(monkeypatch, api_key):
    monkeypatch.setenv("GEMINI_API_KEY", api_key)

    with pytest.raises(google_extractor.GoogleAIStudioConfigurationError):
        google_extractor.extract_entities_with_google("test message")
