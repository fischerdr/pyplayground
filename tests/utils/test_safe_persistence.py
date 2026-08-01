#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for pyplayground/utils/safe_persistence.py.

Covers the two general-purpose helpers in isolation, independent of any
call site: atomic_write() (temp-file-plus-os.replace() atomicity) and
verify_before_write() (capture/reload/compare/dispatch only, no domain
vocabulary). Call-site migrations (config_utils.save_json_config(),
glossary.py, global_vocabulary.py, GlossaryCoordinator.save_snapshot(),
open_retranslate_popup()'s stale-popup guard) keep their own existing
regression coverage in their respective test files; this file is only
about the shared mechanism.
"""

import os

import pytest

from pyplayground.utils.safe_persistence import atomic_write, verify_before_write


class TestAtomicWrite:
    """Tests for atomic_write()'s temp-file-plus-os.replace() mechanism."""

    def test_writes_text_content(self, tmp_path):
        target = tmp_path / "data.txt"

        atomic_write(target, "hello world")

        assert target.read_text(encoding="utf-8") == "hello world"

    def test_writes_bytes_content(self, tmp_path):
        target = tmp_path / "data.bin"

        atomic_write(target, b"\x00\x01\x02")

        assert target.read_bytes() == b"\x00\x01\x02"

    def test_overwrites_existing_file_completely(self, tmp_path):
        target = tmp_path / "data.txt"
        target.write_text("old content that is much longer than the new one", encoding="utf-8")

        atomic_write(target, "new")

        assert target.read_text(encoding="utf-8") == "new"

    def test_no_leftover_temp_file_after_successful_write(self, tmp_path):
        target = tmp_path / "data.txt"

        atomic_write(target, "hello")

        remaining = list(tmp_path.iterdir())
        assert remaining == [target]

    def test_mid_write_failure_leaves_original_target_completely_untouched(self, tmp_path, monkeypatch):
        """Simulate a crash between the temp-file write and os.replace() -- the original target must be untouched, not truncated or partially overwritten.

        Forces os.replace() itself to raise, after the temp file has
        already been fully written and fsynced -- the same failure point
        a real crash/power-loss between write and replace would hit.
        """
        target = tmp_path / "data.txt"
        original_content = "this is the original, untouched content"
        target.write_text(original_content, encoding="utf-8")

        def failing_replace(src, dst):
            raise OSError("simulated mid-write failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError, match="simulated mid-write failure"):
            atomic_write(target, "new content that must never land")

        assert target.read_text(encoding="utf-8") == original_content, "original target must be byte-for-byte untouched after a failed replace"

    def test_mid_write_failure_cleans_up_temp_file(self, tmp_path, monkeypatch):
        target = tmp_path / "data.txt"
        target.write_text("original", encoding="utf-8")

        def failing_replace(src, dst):
            raise OSError("simulated mid-write failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError):
            atomic_write(target, "new content")

        remaining = list(tmp_path.iterdir())
        assert remaining == [target], "the temp file must be removed on failure, not left behind"

    def test_write_failure_before_replace_leaves_target_untouched_and_no_temp_file(self, tmp_path, monkeypatch):
        """A failure while writing the temp file itself (not just at replace()) must also leave the target untouched and clean up the temp file."""
        target = tmp_path / "data.txt"
        target.write_text("original", encoding="utf-8")

        real_open = open

        def failing_open(path, mode="r", **kwargs):
            if str(path).endswith(".tmp"):
                raise OSError("simulated write failure")
            return real_open(path, mode, **kwargs)

        monkeypatch.setattr("builtins.open", failing_open)

        with pytest.raises(OSError, match="simulated write failure"):
            atomic_write(target, "new content")

        monkeypatch.undo()
        assert target.read_text(encoding="utf-8") == "original"
        remaining = list(tmp_path.iterdir())
        assert remaining == [target]

    def test_temp_filename_is_unique_per_write(self, tmp_path):
        """Two concurrent writers to the same target must not collide on the same temp filename (PID + random suffix, not a fixed path + '.tmp')."""
        target = tmp_path / "data.txt"
        seen_tmp_names = []
        real_replace = os.replace

        def capturing_replace(src, dst):
            seen_tmp_names.append(os.path.basename(src))
            real_replace(src, dst)

        import pyplayground.utils.safe_persistence as safe_persistence_module

        original_replace = safe_persistence_module.os.replace
        safe_persistence_module.os.replace = capturing_replace
        try:
            atomic_write(target, "first")
            atomic_write(target, "second")
        finally:
            safe_persistence_module.os.replace = original_replace

        assert len(seen_tmp_names) == 2
        assert seen_tmp_names[0] != seen_tmp_names[1], "each write must use a unique temp filename"


class TestVerifyBeforeWrite:
    """Tests for verify_before_write()'s capture/reload/compare/dispatch mechanism, using a neutral placeholder domain."""

    def test_unchanged_marker_dispatches_to_write_as_is(self):
        """When the reloaded marker still matches the captured one, local_data is returned unchanged and on_divergence is never called."""
        divergence_calls = []

        result = verify_before_write(
            captured_marker="v1",
            reload_current=lambda: "v1",
            on_divergence=lambda current, local: divergence_calls.append((current, local)) or "unexpected",
            local_data={"count": 5},
        )

        assert result == {"count": 5}
        assert divergence_calls == []

    def test_changed_marker_dispatches_to_divergence_callback_with_right_arguments(self):
        """When the reloaded marker differs, on_divergence() is called with (current_marker, local_data) and its return value is used instead of local_data."""
        divergence_calls = []

        def on_divergence(current_marker, local_data):
            divergence_calls.append((current_marker, local_data))
            return {"merged": True}

        result = verify_before_write(
            captured_marker="v1",
            reload_current=lambda: "v2",
            on_divergence=on_divergence,
            local_data={"count": 5},
        )

        assert result == {"merged": True}
        assert divergence_calls == [("v2", {"count": 5})]

    def test_reload_current_is_called_exactly_once(self):
        """reload_current() must be invoked immediately before the comparison, not earlier and not more than once per call."""
        call_count = {"value": 0}

        def reload_current():
            call_count["value"] += 1
            return "v1"

        verify_before_write(
            captured_marker="v1",
            reload_current=reload_current,
            on_divergence=lambda current, local: local,
            local_data="data",
        )

        assert call_count["value"] == 1

    def test_default_markers_match_uses_equality(self):
        """With no markers_match override, comparison defaults to == -- covers a string marker (e.g. an updated_at timestamp)."""
        result = verify_before_write(
            captured_marker="2026-01-01T00:00:00+00:00",
            reload_current=lambda: "2026-01-01T00:00:00+00:00",
            on_divergence=lambda current, local: "should not be called",
            local_data="unchanged",
        )

        assert result == "unchanged"

    def test_custom_markers_match_callback_is_used_when_provided(self):
        """A caller-supplied markers_match callback (e.g. object-identity comparison for a non-hashable/non-comparable marker shape) overrides the default ==."""

        class Placeholder:
            """Neutral placeholder object standing in for a caller's domain-specific marker shape."""

        a = Placeholder()
        b = Placeholder()

        # Identity comparison: a and b are unequal objects, so markers_match
        # using `is` must report divergence even though nothing else about
        # them differs.
        result = verify_before_write(
            captured_marker=a,
            reload_current=lambda: b,
            on_divergence=lambda current, local: "diverged",
            local_data="original",
            markers_match=lambda captured, current: captured is current,
        )

        assert result == "diverged"

        # Same object both times: markers_match using `is` must report a match.
        result = verify_before_write(
            captured_marker=a,
            reload_current=lambda: a,
            on_divergence=lambda current, local: "should not be called",
            local_data="original",
            markers_match=lambda captured, current: captured is current,
        )

        assert result == "original"

    def test_no_domain_vocabulary_leaks_into_helper_behavior(self):
        """Sanity check that the helper works against a neutral placeholder domain (an inventory-count marker), not anything glossary/episode-shaped."""

        def reload_inventory_version():
            return 3

        def resolve_inventory_conflict(current_version, local_snapshot):
            return {"version": current_version, "count": local_snapshot["count"] + 1}

        result = verify_before_write(
            captured_marker=1,
            reload_current=reload_inventory_version,
            on_divergence=resolve_inventory_conflict,
            local_data={"count": 10},
        )

        assert result == {"version": 3, "count": 11}
