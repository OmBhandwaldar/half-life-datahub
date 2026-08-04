"""Web ledger.

Memory integrity is invisible by nature — a rotting memory looks exactly like a
healthy one until someone acts on it. The ledger makes the decay legible: what
each memory rests on, what moved underneath it, and what that cost its score.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..client import HalfLifeClient
from ..config import Config
from ..models import Memory, MemoryStatus
from ..store import MemoryStore

TEMPLATES = Path(__file__).parent / "templates"


def create_app(config: Config | None = None) -> FastAPI:
    app = FastAPI(title="Half-Life ledger", docs_url=None, redoc_url=None)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )

    def _memories() -> list[Memory]:
        store = MemoryStore(HalfLifeClient(config))
        return store.list_memories()

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        memories = _memories()
        template = env.get_template("ledger.html")
        return HTMLResponse(
            template.render(
                memories=[_view(m) for m in memories],
                counts=_counts(memories),
                total=len(memories),
                gms_url=(config or Config.from_env()).gms_url,
            )
        )

    @app.get("/api/memories")
    def api_memories() -> JSONResponse:
        memories = _memories()
        return JSONResponse(
            {"total": len(memories), "counts": _counts(memories),
             "memories": [_view(m) for m in memories]}
        )

    return app


def _counts(memories: list[Memory]) -> dict[str, int]:
    return {
        status.value: sum(1 for m in memories if m.status is status)
        for status in MemoryStatus
    }


def _view(memory: Memory) -> dict:
    return {
        "urn": memory.urn,
        "id": memory.id,
        "title": memory.title,
        "text": memory.text,
        "status": memory.status.value,
        "score": memory.integrity_score,
        "dependencies": [
            {"urn": urn, "label": _label(urn), "fingerprint": memory.fingerprints.get(urn, "—")}
            for urn in memory.dependencies
        ],
        "reason": memory.invalidation_reason,
        "recorded_at": memory.recorded_at,
        "last_validated_at": memory.last_validated_at,
    }


def _label(urn: str) -> str:
    """Readable name for a URN, without losing which platform it came from."""
    if urn.startswith("urn:li:glossaryTerm:"):
        return "glossary term"
    if "," in urn:
        parts = urn.split(",")
        if len(parts) >= 2:
            name = parts[-2].strip()
            platform = ""
            if "dataPlatform:" in urn:
                platform = urn.split("dataPlatform:")[1].split(",")[0]
            return f"{platform}: {name}" if platform else name
    return urn.rsplit(":", 1)[-1]
