"""Smart field filtering using LLM for structure-only mode.

This module provides intelligent field reduction when template paths exceed
a threshold, helping AI agents focus on business-relevant data while reducing
token consumption.

Caching:
    Filtering decisions are cached in-memory based on field structure fingerprint.
    Repeated queries to APIs with identical structure reuse cached decisions,
    providing 66% cost reduction and 67% latency improvement.

    Cache is automatically managed via LRU eviction (maxsize=100) and cleared
    on process restart.
"""

import hashlib
import logging
from functools import lru_cache

from pydantic import BaseModel

from pflow.core.exceptions import LLMCallError
from pflow.core.llm_client import complete
from pflow.core.llm_reasoning_map import map_reasoning_options
from pflow.core.llm_utils import parse_structured_response

logger = logging.getLogger(__name__)

# Smart filtering threshold - triggers LLM filtering when field count exceeds this value.
# Originally planned as 50, lowered to 30 based on performance analysis showing:
# - High accuracy (95-100%) at depth 1-5 for 30+ field APIs
# - Better UX for moderately complex APIs (30-50 field range)
# See: .taskmaster/tasks/task_89/implementation/FINAL-SMART-FILTERING-ANALYSIS.md
SMART_FILTER_THRESHOLD = 30


class FilteredFields(BaseModel):
    """Structured output schema for smart field filtering."""

    included_fields: list[str]
    reasoning: str  # For validation, not displayed to user


def _calculate_fingerprint(fields: tuple[tuple[str, str], ...]) -> str:
    """Calculate unique fingerprint for field structure.

    Args:
        fields: Tuple of (path, type) tuples (must be hashable)

    Returns:
        MD5 hash of sorted field paths

    Note:
        - Only field paths are hashed (types ignored)
        - Fields are sorted for consistency
        - Values are never included in fingerprint

    Examples:
        >>> fields = (("result.name", "str"), ("result.id", "int"))
        >>> _calculate_fingerprint(fields)  # MD5 of sorted, comma-joined paths
        '985fb8beb6442b620e98c84797e54ad8'
    """
    # Extract paths only (ignore types)
    paths = [path for path, _ in fields]

    # Sort for order independence
    sorted_paths = sorted(paths)

    # Hash the sorted paths
    path_string = ",".join(sorted_paths)
    return hashlib.md5(path_string.encode(), usedforsecurity=False).hexdigest()


def smart_filter_fields(
    fields: list[tuple[str, str]],
    threshold: int = SMART_FILTER_THRESHOLD,
) -> list[tuple[str, str]]:
    """Filter template paths using Haiku 4.5 when count exceeds threshold.

    This function reduces large field sets (e.g., 200+ GitHub issue fields) to
    8-15 business-relevant fields that AI agents need for workflow orchestration.

    Args:
        fields: List of (path, type) tuples like [("result[0].title", "string"), ...]
        threshold: Trigger filtering when field count exceeds this (default: 30)

    Returns:
        Filtered list of (path, type) tuples, or original list if:
        - Field count <= threshold (no filtering needed)
        - LLM call fails (fallback to show all)
        - Filtered result is empty (safety fallback)

    Future Enhancement:
        Add optional 'context' parameter (e.g., "fraud detection", "payment processing")
        to guide LLM filtering toward domain-specific fields. Would require cache
        invalidation since same field structure + different context = different result.
        Usage: `probe http url=... --filter-context="fraud detection"`

    Examples:
        With a large field set, an LLM call reduces it to the most relevant
        fields (requires an LLM API key, so this is not run as a doctest)::

            fields = [("result[0].id", "int"), ("result[0].title", "str"), ...]  # 200 fields
            filtered = smart_filter_fields(fields, threshold=50)
            len(filtered)  # ~12 — reduced to business-relevant fields

        Field sets at or below the threshold are returned unchanged:
        >>> small_fields = [("status", "str"), ("count", "int")]
        >>> smart_filter_fields(small_fields, threshold=50) == small_fields
        True
    """
    # Don't filter if below threshold
    if len(fields) <= threshold:
        logger.debug(f"Field count ({len(fields)}) <= threshold ({threshold}), skipping smart filter")
        return fields

    logger.info(
        f"Smart filtering triggered: {len(fields)} fields > {threshold} threshold",
        extra={"field_count": len(fields), "threshold": threshold},
    )

    try:
        # Build field list for prompt
        field_list = "\n".join([f"- {path} ({type_info})" for path, type_info in fields])

        # TODO: Add optional context parameter for domain-specific filtering
        # context = kwargs.get('context')  # e.g., "fraud detection", "payment processing"
        # Cache key would need to include: hash(fields + context)
        # Prompt would include: f"USER CONTEXT: {context}\nPrioritize fields relevant to: {context}"

        # Construct prompt
        prompt = f"""You are filtering fields from an API response to show only business-relevant data for AI workflow orchestration.

INPUT FIELDS ({len(fields)} total):

Note: Array fields like result[0].login represent the structure of ALL array items.
The [0] index is just a sample - each field exists on every array item.
Return field paths exactly as shown, each path only once.

{field_list}

FILTER RULES:
- REMOVE: URLs, internal IDs, timestamps, metadata fields, technical details, API infrastructure fields
- KEEP: Titles, content, status, user-facing data, business information, relationship data, array item structure
- TARGET: 8-15 fields maximum (be aggressive in filtering)

ARRAY FIELD PRIORITY:
- Array item fields like items[0].name show the structure of EACH item in that array
- DEPTH DOES NOT MATTER: Arrays can be at any nesting level (items, data.items, data.nested.items)
- When an array is business-relevant, ALWAYS include 2-5 key [0] fields regardless of depth
- This is CRITICAL: agents need to know what fields exist in array items to process them

Examples at different depths:
- Top level: Keep items[0].name, items[0].status | Filter items[0].internal_id
- Nested: Keep data.items[0].title, data.items[0].price | Filter data.items[0].metadata_url
- Deep: Keep data.nested.items[0].value, data.nested.items[0].type | Filter data.nested.items[0].debug_info

Balance: Show both the array (data.nested.items) AND its key fields (data.nested.items[0].value)

REASONING:
An AI agent is orchestrating workflows and needs to decide which data to route between nodes.
It does NOT need to see the actual data values - just understand what fields exist.
Focus on fields that represent meaningful business entities and their relationships.
For arrays, showing sample item fields is crucial for the agent to know what's accessible.

Return ONLY the field paths (without type annotations) that the agent needs to see."""

        # Get filtering model from settings → auto-detect → fallback
        from pflow.core.llm_config import get_model_for_feature

        filtering_model = get_model_for_feature("filtering")

        # Trivial classification — request minimum reasoning. The canonical
        # translator handles per-provider mapping (thinking_budget=0 on Gemini
        # 2.5, thinking_level=minimal on Gemini 3, thinking=False on Anthropic,
        # no-op on non-reasoning models), so we don't duplicate provider
        # detection here.
        reasoning_kwargs = map_reasoning_options(filtering_model, "none", None, None)

        # Pydantic class → JSON Schema dict (the adapter accepts only dicts).
        response = complete(
            model=filtering_model,
            prompt=prompt,
            temperature=0.0,
            schema=FilteredFields.model_json_schema(),
            reasoning_kwargs=reasoning_kwargs or None,
        )

        # Parse structured response
        result = parse_structured_response(response, FilteredFields, model=filtering_model)
        included_paths = result["included_fields"]

        logger.debug(
            f"LLM returned {len(included_paths)} filtered fields",
            extra={
                "original_count": len(fields),
                "filtered_count": len(included_paths),
                "reasoning": result["reasoning"],
            },
        )

        # Match LLM-selected paths back to original tuples (preserves type info)
        included_set = set(included_paths)
        filtered = [(path, type_info) for path, type_info in fields if path in included_set]

        # Safety check: if LLM returned empty or filtered everything, fallback to original
        if not filtered:
            logger.warning(
                "Smart filter returned empty result, using original fields",
                extra={"llm_returned": len(included_paths)},
            )
            return fields

        logger.info(
            f"Smart filtering complete: {len(fields)} → {len(filtered)} fields",
            extra={"reduction_ratio": f"{len(filtered)}/{len(fields)}"},
        )

        return filtered

    except (LLMCallError, ConnectionError, OSError) as e:
        # Graceful degradation for the failure modes filtering can't avoid:
        # - LLMCallError: umbrella covers EVERY adapter failure mode —
        #   deterministic (UnknownModelError, MissingApiKeyError,
        #   InvalidRequestError, LLMResponseParseError) AND transient
        #   (LLMTransientError covers Timeout/RateLimit/InternalServerError).
        #   The architectural seal means we never need to import
        #   ``litellm.exceptions`` here; one typed catch is enough.
        # - ConnectionError / OSError: network or socket failure outside the
        #   adapter (e.g. DNS lookup before httpx is reached).
        # NOTE: Umbrella catch must remain LLMCallError-narrow. Broadening
        # to bare Exception would swallow KeyboardInterrupt, SystemExit, and
        # programming bugs (AttributeError, TypeError, KeyError) that should
        # surface as test failures instead of silently degrading UX.
        logger.warning(
            f"Smart filter failed, returning all {len(fields)} fields unfiltered: {e}",
            extra={"error_type": type(e).__name__, "error_message": str(e)},
        )
        return fields


def smart_filter_fields_cached(
    fields_tuple: tuple[tuple[str, str], ...],
    threshold: int = SMART_FILTER_THRESHOLD,
) -> tuple[tuple[str, str], ...]:
    """Public wrapper that normalizes field order before caching.

    This function sorts fields by path before calling the cached implementation,
    ensuring that different field orders produce the same cache key.
    """
    # Sort fields by path (first element of tuple) for consistent cache key
    sorted_fields = tuple(sorted(fields_tuple, key=lambda x: x[0]))

    # Call cached implementation with normalized input
    return _smart_filter_fields_cached_impl(sorted_fields, threshold)


@lru_cache(maxsize=100)
def _smart_filter_fields_cached_impl(
    fields_tuple: tuple[tuple[str, str], ...],
    threshold: int = 30,
) -> tuple[tuple[str, str], ...]:
    """Cached version of smart_filter_fields.

    Uses in-memory LRU cache to avoid redundant LLM calls for identical
    field structures. The filtering decision depends only on field names
    and structure, not data values, so caching is safe.

    Args:
        fields_tuple: Tuple of (path, type) tuples (must be hashable for caching)
        threshold: Trigger filtering when field count exceeds this

    Returns:
        Tuple of filtered (path, type) tuples

    Cache Behavior:
        - Cache key: MD5 hash of sorted field paths
        - Cache size: 100 entries (LRU eviction)
        - Cache lifetime: Process lifetime (cleared on restart)
        - Cache hit: 0ms, $0 (instant return)
        - Cache miss: 2.5-3.5s, ~$0.003 (calls smart_filter_fields)

    Performance Impact:
        - 66% cost reduction on cache hits
        - 67% latency improvement (2.8s → 0ms)
        - Typical hit rate: 40-90% depending on usage pattern

    Examples:
        Identical field structures reuse the cached result instead of calling
        the LLM again (requires an LLM API key, so this is not run as a
        doctest)::

            fields = tuple([("result.name", "str"), ("result.id", "int")])
            smart_filter_fields_cached(fields, threshold=1)  # first call: cache miss, ~2.8s
            smart_filter_fields_cached(fields, threshold=1)  # second call: cache hit, 0ms
    """
    # Calculate fingerprint for logging
    fingerprint = _calculate_fingerprint(fields_tuple)

    # Get cache info for logging
    cache_info = _smart_filter_fields_cached_impl.cache_info()

    logger.debug(
        f"Smart filter cache lookup: fingerprint={fingerprint[:8]}..., "
        f"hits={cache_info.hits}, misses={cache_info.misses}, "
        f"size={cache_info.currsize}/{cache_info.maxsize}"
    )

    # Convert to list for processing
    fields_list = list(fields_tuple)

    # Call original smart_filter_fields
    filtered_list = smart_filter_fields(fields_list, threshold)

    # Convert back to tuple for caching
    return tuple(filtered_list)


def get_cache_stats() -> dict[str, float | int]:
    """Get smart filter cache statistics.

    Returns:
        Dictionary with cache metrics:
        - hits: Number of cache hits
        - misses: Number of cache misses
        - size: Current cache size
        - maxsize: Maximum cache size
        - hit_rate: Cache hit percentage (0-100)

    Examples:
        >>> from pflow.registry.smart_filter import get_cache_stats
        >>> sorted(get_cache_stats())
        ['hit_rate', 'hits', 'maxsize', 'misses', 'size']
    """
    info = _smart_filter_fields_cached_impl.cache_info()

    total = info.hits + info.misses
    hit_rate = (info.hits / total * 100) if total > 0 else 0.0

    return {
        "hits": info.hits,
        "misses": info.misses,
        "size": info.currsize,
        "maxsize": info.maxsize if info.maxsize is not None else 0,
        "hit_rate": round(hit_rate, 1),
    }


def clear_cache() -> None:
    """Clear the smart filter cache.

    Useful for:
    - Testing (start with clean cache)
    - Memory management (free cache memory)
    - Forcing re-filtering (after prompt changes)

    Note:
        Cache is automatically cleared on process restart.

    Examples:
        >>> from pflow.registry.smart_filter import clear_cache
        >>> clear_cache()  # cache is now empty; the next call will be a cache miss
    """
    _smart_filter_fields_cached_impl.cache_clear()
    logger.info("Smart filter cache cleared")
