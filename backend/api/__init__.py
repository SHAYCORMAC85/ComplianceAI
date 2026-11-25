"""
FastAPI API Endpoints Package
"""

from .routes_documents import router as documents_router
from .routes_review import router as review_router

__all__ = ["documents_router", "review_router"]
