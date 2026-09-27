"""FastAPI entrypoint for the dispute intake & triage service."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Dispute Intake & Triage",
    description="AI-first banking dispute intake and triage system",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check used by frontend and docker-compose."""
    return {"status": "ok", "service": "dispute-triage"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Dispute Intake & Triage API",
        "docs": "/docs",
        "health": "/health",
    }
