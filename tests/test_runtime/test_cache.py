"""Tests for the runtime memoization cache module.

Covers: cache key computation, put/get lifecycle, TTL eviction, read-disabled mode,
graceful degradation on corrupted DB, and concurrent access safety.
"""

import sqlite3
import threading
import time
from typing import Any

from pflow.runtime.cache import (
    MemoizationCache,
    compute_batch_cache_key,
    compute_node_cache_key,
)

# ---------------------------------------------------------------------------
# Basic put / get lifecycle
# ---------------------------------------------------------------------------


def test_put_get_cycle(tmp_path):
    """Storing an entry and retrieving it returns the same action and output."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("key1", "node-a", "/wf.pflow.md", "default", {"stdout": "hello"})
    result = cache.get("key1")

    assert result is not None
    action, output = result
    assert action == "default"
    assert output == {"stdout": "hello"}


def test_cache_miss(tmp_path):
    """Looking up a key that was never stored returns None."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    result = cache.get("nonexistent-key")
    assert result is None


# ---------------------------------------------------------------------------
# TTL and eviction
# ---------------------------------------------------------------------------


def test_ttl_eviction(tmp_path):
    """Entries older than TTL are removed by evict_expired()."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, ttl_seconds=3600)

    cache.put("old", "n1", "/wf.pflow.md", "default", {"v": 1})
    cache.put("new", "n2", "/wf.pflow.md", "default", {"v": 2})

    # Backdate the "old" entry by 2 hours
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
        (time.time() - 7200, "old"),
    )
    conn.commit()
    conn.close()

    removed = cache.evict_expired()
    assert removed == 1

    # "old" is gone, "new" is still there
    assert cache.get("old") is None
    assert cache.get("new") is not None


def test_expired_entry_deleted_on_get(tmp_path):
    """Getting an expired entry deletes it from the DB and returns None."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, ttl_seconds=3600)

    cache.put("key1", "n1", "/wf.pflow.md", "default", {"v": 1})

    # Backdate entry beyond TTL
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
        (time.time() - 7200, "key1"),
    )
    conn.commit()
    conn.close()

    # get() should return None for the expired entry
    assert cache.get("key1") is None

    # Verify the row was actually deleted from the database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM cache_entries WHERE cache_key = ?", ("key1",))
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# Overwrite and clear
# ---------------------------------------------------------------------------


def test_overwrite_same_key(tmp_path):
    """Putting the same key again overwrites the previous output."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("k", "n1", "/wf.pflow.md", "default", {"version": 1})
    cache.put("k", "n1", "/wf.pflow.md", "default", {"version": 2})

    result = cache.get("k")
    assert result is not None
    _, output = result
    assert output == {"version": 2}


def test_clear_all(tmp_path):
    """clear() with no arguments removes all entries."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("a", "n1", "/wf1.pflow.md", "default", {"x": 1})
    cache.put("b", "n2", "/wf2.pflow.md", "default", {"x": 2})

    removed = cache.clear()
    assert removed == 2

    assert cache.get("a") is None
    assert cache.get("b") is None


def test_clear_by_workflow(tmp_path):
    """clear(workflow_path) only removes entries for that specific workflow."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("a", "n1", "/wf1.pflow.md", "default", {"x": 1})
    cache.put("b", "n2", "/wf2.pflow.md", "default", {"x": 2})
    cache.put("c", "n3", "/wf1.pflow.md", "default", {"x": 3})

    removed = cache.clear(workflow_path="/wf1.pflow.md")
    assert removed == 2

    # wf1 entries gone
    assert cache.get("a") is None
    assert cache.get("c") is None
    # wf2 entry intact
    assert cache.get("b") is not None


# ---------------------------------------------------------------------------
# read_enabled flag
# ---------------------------------------------------------------------------


def test_read_disabled(tmp_path):
    """When read_enabled=False, get() always returns None even for stored entries."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, read_enabled=False)

    cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 1})
    assert cache.get("k") is None


def test_write_still_works_when_read_disabled(tmp_path):
    """put() writes to DB even when read_enabled=False; a read-enabled cache can retrieve it."""
    db_path = tmp_path / "cache.db"
    write_cache = MemoizationCache(db_path=db_path, read_enabled=False)
    write_cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 42})

    # A separate cache instance with reads enabled can see the entry
    read_cache = MemoizationCache(db_path=db_path, read_enabled=True)
    result = read_cache.get("k")
    assert result is not None
    _, output = result
    assert output == {"v": 42}


def test_get_with_age_returns_created_at(tmp_path):
    """get_with_age() returns the stored entry plus its timestamp."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    before = time.time()
    cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 1})
    result = cache.get_with_age("k")

    assert result is not None
    action, output, created_at = result
    assert action == "default"
    assert output == {"v": 1}
    assert created_at >= before
    assert created_at <= time.time()


def test_get_latest_for_node_returns_newest_entry(tmp_path):
    """get_latest_for_node() returns the most recent entry for that node_id."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("old-key", "node-a", "/wf.pflow.md", "default", {"version": 1})
    time.sleep(0.01)
    cache.put("new-key", "node-a", "/wf.pflow.md", "default", {"version": 2})

    result = cache.get_latest_for_node("node-a")

    assert result is not None
    output, created_at = result
    assert output == {"version": 2}
    assert isinstance(created_at, float)


def test_get_latest_for_node_returns_two_tuple_unchanged(tmp_path):
    """Existing get_latest_for_node() API stays a two-tuple."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("key", "node-a", "/wf.pflow.md", "default", {"version": 1})

    result = cache.get_latest_for_node("node-a", workflow_path="/wf.pflow.md")

    assert result is not None
    output, created_at = result
    assert output == {"version": 1}
    assert isinstance(created_at, float)


def test_get_latest_for_node_with_cache_key_returns_three_tuple(tmp_path):
    """The additive freshness-check API includes the stored cache_key."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    cache.put("stored-key", "node-a", "/wf.pflow.md", "default", {"version": 1})

    result = cache.get_latest_for_node_with_cache_key("node-a", workflow_path="/wf.pflow.md")

    assert result is not None
    output, created_at, cache_key = result
    assert output == {"version": 1}
    assert isinstance(created_at, float)
    assert cache_key == "stored-key"


def test_get_with_age_respects_ttl(tmp_path):
    """Expired entries are hidden by get_with_age()."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, ttl_seconds=60)

    cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 1})
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
        (time.time() - 3600, "k"),
    )
    conn.commit()
    conn.close()

    assert cache.get_with_age("k") is None


def test_get_with_age_respects_read_enabled(tmp_path):
    """Read-disabled cache returns None for get_with_age()."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, read_enabled=False)

    cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 1})

    assert cache.get_with_age("k") is None


def test_get_latest_for_node_returns_none_for_unknown_node(tmp_path):
    """Unknown node_id returns None."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    assert cache.get_latest_for_node("missing-node") is None


def test_get_latest_for_node_respects_ttl(tmp_path):
    """Expired latest entries are treated as misses."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, ttl_seconds=60)

    cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 1})
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE cache_entries SET created_at = ? WHERE node_id = ?",
        (time.time() - 3600, "n1"),
    )
    conn.commit()
    conn.close()

    assert cache.get_latest_for_node("n1") is None


def test_idx_node_id_created_at_exists(tmp_path):
    """Schema initialization creates the node_id+created_at index."""
    db_path = tmp_path / "cache.db"
    MemoizationCache(db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA index_list(cache_entries)").fetchall()
    finally:
        conn.close()

    index_names = {row[1] for row in rows}
    assert "idx_node_id_created_at" in index_names


# ---------------------------------------------------------------------------
# Cache key computation — node keys
# ---------------------------------------------------------------------------


def test_compute_node_cache_key_determinism():
    """Same config_hash and resolved_inputs always produce the same key."""
    key1 = compute_node_cache_key("hash_abc", resolved_inputs={"prompt": "hello"})
    key2 = compute_node_cache_key("hash_abc", resolved_inputs={"prompt": "hello"})
    assert key1 == key2


def test_compute_node_cache_key_different_inputs():
    """Different resolved_inputs produce different keys."""
    key1 = compute_node_cache_key("hash_abc", resolved_inputs={"prompt": "hello"})
    key2 = compute_node_cache_key("hash_abc", resolved_inputs={"prompt": "world"})
    assert key1 != key2


def test_compute_node_cache_key_none_vs_empty_inputs():
    """No resolved_inputs vs empty dict produce different keys (different hash content)."""
    key_none = compute_node_cache_key("hash_abc")
    key_empty = compute_node_cache_key("hash_abc", resolved_inputs={})
    assert key_none != key_empty


def test_compute_node_cache_key_dict_order_irrelevant():
    """Dict key order does not affect the cache key (JSON sort_keys=True)."""
    key1 = compute_node_cache_key("h", resolved_inputs={"a": 1, "b": 2})
    key2 = compute_node_cache_key("h", resolved_inputs={"b": 2, "a": 1})
    assert key1 == key2


def test_compute_node_cache_key_filters_source_line_keys():
    """GH #357: ``_*_source_line`` keys must be filtered from the cache key
    so cosmetic line-shifts (workflow edits, saved-library frontmatter
    growth on each run) don't invalidate the cache.

    Mirrors the existing filter in ``compute_node_config`` for the same
    reason. Without this filter, every ``pflow save`` workflow re-executes
    on every invocation because frontmatter mutation shifts source lines.
    """
    no_lines = {"prompt": "hello", "model": "x"}
    with_lines = {"prompt": "hello", "model": "x", "_prompt_source_line": 23, "_model_source_line": 19}
    with_different_lines = {**with_lines, "_prompt_source_line": 56, "_model_source_line": 52}
    assert compute_node_cache_key("h", no_lines) == compute_node_cache_key("h", with_lines), (
        "presence of _*_source_line keys must NOT change the cache key"
    )
    assert compute_node_cache_key("h", with_lines) == compute_node_cache_key("h", with_different_lines), (
        "different _*_source_line values must NOT change the cache key (cosmetic shifts)"
    )


def test_compute_node_cache_key_preserves_real_input_changes_alongside_line_shifts():
    """Filter must not be over-broad — real input changes still differentiate."""
    a = {"prompt": "hello", "_prompt_source_line": 10}
    b = {"prompt": "world", "_prompt_source_line": 20}
    assert compute_node_cache_key("h", a) != compute_node_cache_key("h", b)


def test_compute_node_cache_key_filter_only_targets_suffix():
    """Filter matches the ``_source_line`` suffix only — keys that happen to
    contain ``source_line`` mid-name are NOT filtered."""
    a = {"source_line_other": "x"}  # NOT a _*_source_line key
    b = {"line_source": "x"}  # NOT a _*_source_line key
    c = {"_x_source_line": 1}  # IS a _*_source_line key
    # a vs missing-key: distinct
    assert compute_node_cache_key("h", a) != compute_node_cache_key("h", {})
    # b vs missing-key: distinct
    assert compute_node_cache_key("h", b) != compute_node_cache_key("h", {})
    # c vs missing-key: SAME (filtered out)
    assert compute_node_cache_key("h", c) == compute_node_cache_key("h", {})


def test_compute_node_cache_key_filters_all_metadata_suffixes():
    """Filter covers every parser-injected metadata suffix — not just the
    singular ``_source_line``. ``markdown_parser.py`` also writes ``_source_lines``
    (plural dict per code block) and ``_source_files`` (per-file-ref metadata).

    Without this broader filter, the same regression class as GH #357 reopens
    on the day either suffix lands in ``resolved_inputs`` (e.g. via a future
    template-resolution path that includes nested node config). Defensive
    tightening per CR-1430 C4.
    """
    base: dict[str, Any] = {"prompt": "hello"}
    # Each metadata-suffix key must be filtered:
    for metadata_key in ("_x_source_line", "_x_source_lines", "_x_source_files"):
        with_meta = {**base, metadata_key: {"some": "value"}}
        assert compute_node_cache_key("h", base) == compute_node_cache_key("h", with_meta), (
            f"{metadata_key!r} must be filtered (cosmetic metadata, shifts on every edit)"
        )

    # User-defined keys that LOOK metadata-ish but don't end in a known
    # metadata suffix must NOT be filtered (over-broad-filter regression):
    user_input = {**base, "_user_internal": "data"}
    assert compute_node_cache_key("h", base) != compute_node_cache_key("h", user_input), (
        "_user_internal is a user-defined input — must NOT be filtered"
    )


# ---------------------------------------------------------------------------
# Cache key computation — batch keys
# ---------------------------------------------------------------------------


def test_compute_batch_cache_key_determinism():
    """Same inputs always produce the same batch cache key."""
    config = {"items_template": "${data}", "item_alias": "item"}
    key1 = compute_batch_cache_key("hash_abc", config, ["a", "b", "c"])
    key2 = compute_batch_cache_key("hash_abc", config, ["a", "b", "c"])
    assert key1 == key2


def test_compute_batch_cache_key_different_items():
    """Different resolved_items produce different batch cache keys."""
    config = {"items_template": "${data}", "item_alias": "item"}
    key1 = compute_batch_cache_key("hash_abc", config, ["a", "b", "c"])
    key2 = compute_batch_cache_key("hash_abc", config, ["x", "y", "z"])
    assert key1 != key2


def test_compute_batch_cache_key_different_config():
    """Different batch config produces different batch cache keys."""
    items = ["a", "b"]
    key1 = compute_batch_cache_key("h", {"item_alias": "item"}, items)
    key2 = compute_batch_cache_key("h", {"item_alias": "row"}, items)
    assert key1 != key2


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_corrupted_db_graceful_degradation(tmp_path):
    """Operations on a corrupted database file do not raise; they return defaults."""
    db_path = tmp_path / "cache.db"

    # Write garbage to the file before MemoizationCache tries to init
    db_path.write_bytes(b"this is not a sqlite database at all!!!")

    # Constructor should not crash
    cache = MemoizationCache(db_path=db_path)

    # get should return None, not raise
    assert cache.get("any-key") is None

    # put should not raise
    cache.put("k", "n1", "/wf.pflow.md", "default", {"v": 1})

    # evict should return 0, not raise
    assert cache.evict_expired() == 0

    # clear should return 0, not raise
    assert cache.clear() == 0


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


def test_concurrent_access(tmp_path):
    """Multiple threads can read and write to the same cache without errors."""
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)
    errors: list[Exception] = []
    num_threads = 8
    ops_per_thread = 20

    def worker(thread_id: int) -> None:
        try:
            for i in range(ops_per_thread):
                key = f"t{thread_id}-{i}"
                cache.put(key, f"node-{thread_id}", "/wf.pflow.md", "default", {"tid": thread_id, "i": i})
                result = cache.get(key)
                # The entry we just wrote should be retrievable
                if result is None:
                    errors.append(AssertionError(f"get({key}) returned None immediately after put"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent access errors: {errors}"

    # Verify total entries written
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM cache_entries")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == num_threads * ops_per_thread


# ---------------------------------------------------------------------------
# Key order preservation (GH #333)
# ---------------------------------------------------------------------------


def test_put_get_preserves_dict_key_order(tmp_path):
    """Cache round-trip preserves dict insertion order (not alphabetical).

    Regression guard for GH #333: sort_keys=True in the storage path
    reordered keys, causing downstream cache misses when dicts were
    stringified in templates.
    """
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    output = {
        "zebra": 1,
        "apple": 2,
        "mango": {"nested_z": True, "nested_a": False},
        "banana": [{"z_key": 1, "a_key": 2}],
    }
    cache.put("k", "n", "/wf.pflow.md", "default", output)
    _, restored = cache.get("k")

    assert list(restored.keys()) == ["zebra", "apple", "mango", "banana"]
    assert list(restored["mango"].keys()) == ["nested_z", "nested_a"]
    assert list(restored["banana"][0].keys()) == ["z_key", "a_key"]


def test_cached_output_produces_same_downstream_cache_key(tmp_path):
    """Downstream cache key is identical whether upstream output comes from live run or cache.

    Regression guard for GH #333: sort_keys=True in storage reordered dict keys.
    When a downstream node embeds the upstream dict in a complex template
    (str() stringification), different key order → different prompt string →
    different cache key → false cache miss.

    Mutation: add sort_keys=True to MemoizationCache.put() → this test fails.
    """
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path)

    upstream_output = {
        "zebra": 1,
        "apple": 2,
        "mango": {"nested_z": True, "nested_a": False},
    }

    cache.put("upstream-key", "upstream-node", "/wf.pflow.md", "default", upstream_output)
    _, restored_output = cache.get("upstream-key")

    # Simulate downstream template resolution: dict embedded in a complex
    # template gets stringified via str(), becoming part of resolved_params.
    live_resolved = {"prompt": f"Analyze: {upstream_output}"}
    cached_resolved = {"prompt": f"Analyze: {restored_output}"}

    live_key = compute_node_cache_key("config-hash", live_resolved)
    cached_key = compute_node_cache_key("config-hash", cached_resolved)

    assert live_key == cached_key, (
        f"Cache key diverged: live={live_key}, cached={cached_key}. "
        f"Live keys: {list(upstream_output.keys())}, "
        f"Cached keys: {list(restored_output.keys())}"
    )
