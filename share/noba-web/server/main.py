"""Entry-point alias – allows both invocation styles:

    uvicorn server.app:app   (direct)
    uvicorn server.main:app  (legacy-friendly alias)
"""
from __future__ import annotations
from .app import app  # noqa: F401 – re-export for uvicorn

__all__ = ["app"]
