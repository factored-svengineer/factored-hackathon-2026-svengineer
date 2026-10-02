"""Smoke tests for the FastAPI skeleton."""

from fastapi.testclient import TestClient

from app.graph import google_extractor
from app.graph.extract import extract_entities
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "dispute-triage"


def test_root_links():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["health"] == "/health"


def test_graph_nodes_contract():
    response = client.get("/graph/nodes")
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline"] == ["understand", "decide", "act", "verify", "escalate"]
    assert "auto_resolve" in body["decisions"]


def test_triage_graph_runs(monkeypatch):
    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        lambda text, language_hint=None: extract_entities(text),
    )
    response = client.post(
        "/disputes/triage",
        json={"text": "No reconozco un cargo de 45.99", "language": "es"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "clarify"
    assert body["nodes_visited"][:4] == ["understand", "decide", "act", "verify"]
