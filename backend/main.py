"""
AI Compliance Inspection Agent - FastAPI Main Application
---------------------------------------------------------
Entry point for the backend REST API service.
Registers API routers, CORS middleware, and application health checks.
"""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from backend.security import Ingress
from backend.officers import current_officer
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes_documents import router as documents_router
from backend.api.routes_review import router as review_router
from backend.config import settings

from backend.services.inspection_worker import lifespan

# Initialize FastAPI application
app = FastAPI(
    lifespan=lifespan,
    title="AI Compliance Inspection Agent API",
    description=(
        "Automated compliance document analyzer that extracts sections, "
        "evaluates regulatory rules via an LLM, verifies findings verbatim, "
        "and enforces human officer approval/rejection governance."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(Ingress)

@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({"detail":"Invalid request fields."}, status_code=422)

# Configure Cross-Origin Resource Sharing (CORS) for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["GET","POST","DELETE"],
    allow_headers=["Authorization","Content-Type","Idempotency-Key","X-Authorized-Provider"],
)

# Register API Routers
app.include_router(documents_router, dependencies=[Depends(current_officer)])
app.include_router(review_router)


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint welcoming clients and confirming service status."""
    return {
        "service": "AI Compliance Inspection Agent API",
        "version": "1.0.0",
        "status": "online",
        "documentation": "/docs"
    }


@app.get("/health", tags=["Health"], status_code=status.HTTP_200_OK)
async def health_check():
    """System health check endpoint for uptime monitors."""
    return {
        "status": "healthy",
        "llm_provider": settings.LLM_PROVIDER,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )

