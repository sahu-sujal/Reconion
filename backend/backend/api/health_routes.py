from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=dict[str, str], summary="Health check")
def health() -> dict[str, str]:
    """Return service health information."""
    return {"status": "ok", "service": "recon-platform"}
