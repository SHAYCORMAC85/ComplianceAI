"""
Frontend Configuration
----------------------
Central settings, API target URL, and UI styling theme configuration.
"""

import os

# Backend API Base URL (configurable via environment variable)
BACKEND_BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

# Application Branding
APP_NAME = "ComplianceAI"
APP_SUBTITLE = "AI-Powered Financial Document Inspection Platform"
APP_ICON = "🛡️"

# File Upload Constraints
MAX_FILE_SIZE_MB = 15
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = ["txt", "pdf", "docx"]

# Severity Badge Theme Mapping (Hex Colors for High-Contrast Readable Highlighting)
SEVERITY_COLORS = {
    "LOW": {"bg": "#E8F4FD", "text": "#0B5394", "border": "#A4C2F4"},
    "MEDIUM": {"bg": "#FFF2CC", "text": "#7F6000", "border": "#FFE599"},
    "HIGH": {"bg": "#FCE5CD", "text": "#B45F06", "border": "#F9CB9C"},
    "CRITICAL": {"bg": "#F8CECC", "text": "#990000", "border": "#EA6B66"},
}

# Request Timeout (Set sufficiently higher than backend LLM processing time: 180s)
API_TIMEOUT_SECONDS = int(os.getenv("FRONTEND_TIMEOUT", "180"))

