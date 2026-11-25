"""
Cache Service
-------------
Provides in-memory caching keyed by (document_id, prompt_version, model_id, [chunk_index]).
Prevents redundant, costly LLM API calls when the same document or chunk is inspected
with the exact same prompt version and model.
"""

from collections import OrderedDict
import time
from typing import Any, Dict, List, Optional
from backend.models.finding import RawFinding


class CacheEntry:
    """Wrapper storing value and optional expiration timestamp."""
    def __init__(self, value: Any, expires_at: Optional[float] = None):
        self.value = value
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class CacheService:
    """
    In-memory caching service with hit/miss telemetry and document invalidation.
    """

    def __init__(self, default_ttl_seconds: Optional[int] = None):
        """
        Args:
            default_ttl_seconds: Optional time-to-live in seconds. None means no expiry.
        """
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self.default_ttl = default_ttl_seconds
        self.hits = 0
        self.misses = 0

    @staticmethod
    def build_key(
        document_id: str,
        prompt_version: str,
        model_id: str,
        chunk_index: Optional[int] = None
    ) -> str:
        """
        Constructs a normalized cache key.
        
        Format:
            doc:{document_id}:prompt:{prompt_version}:model:{model_id}[:chunk:{chunk_index}]
        """
        key = f"doc:{document_id}:prompt:{prompt_version}:model:{model_id}"
        if chunk_index is not None:
            key += f":chunk:{chunk_index}"
        return key

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves cached item if present and unexpired.
        """
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None

        if entry.is_expired():
            del self._store[key]
            self.misses += 1
            return None

        self._store.move_to_end(key)
        self.hits += 1
        return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Stores an item in cache with optional TTL.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = (time.time() + ttl) if ttl is not None else None
        self._store[key] = CacheEntry(value=value, expires_at=expires_at)
        self._store.move_to_end(key)
        if len(self._store) > 256:
            self._store.popitem(last=False)

    def has(self, key: str) -> bool:
        """Checks if a valid, unexpired key exists in cache without modifying metrics."""
        entry = self._store.get(key)
        if entry is None or entry.is_expired():
            return False
        return True

    def invalidate_document(self, document_id: str) -> int:
        """
        Invalidates all cache entries associated with a specific document_id.
        
        Returns:
            Number of keys removed.
        """
        prefix = f"doc:{document_id}:"
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    def clear(self) -> None:
        """Clears all cached entries and resets metrics."""
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """Returns cache telemetry statistics."""
        total_requests = self.hits + self.misses
        hit_ratio = (self.hits / total_requests) if total_requests > 0 else 0.0
        return {
            "total_keys": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": round(hit_ratio, 3)
        }

