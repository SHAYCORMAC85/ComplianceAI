"""
Backend Business Logic Services
"""

from .document_processor import (
    DocumentProcessor,
    DocumentProcessorError,
    DocumentEmptyError,
    UnsupportedFileTypeError,
    CorruptFileError,
)
from .rules_engine import (
    RulesEngine,
    RulesEngineError,
    RulesFileNotFoundError,
)
from .cache_service import (
    CacheService,
    CacheEntry,
)
from .llm_orchestrator import (
    LLMOrchestrator,
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMMalformedJSONError,
)
from .offset_calculator import (
    OffsetCalculator,
    OffsetCalculatorError,
    EmptyPassageError,
    PassageNotFoundError,
    OffsetMismatchError,
)
from .validator import (
    Validator,
)

__all__ = [
    "DocumentProcessor",
    "DocumentProcessorError",
    "DocumentEmptyError",
    "UnsupportedFileTypeError",
    "CorruptFileError",
    "RulesEngine",
    "RulesEngineError",
    "RulesFileNotFoundError",
    "CacheService",
    "CacheEntry",
    "LLMOrchestrator",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMMalformedJSONError",
    "OffsetCalculator",
    "OffsetCalculatorError",
    "EmptyPassageError",
    "PassageNotFoundError",
    "OffsetMismatchError",
    "Validator",
]
