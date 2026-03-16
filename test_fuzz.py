#!/usr/bin/env python3
"""Fuzz tests for dirscan using hypothesis."""

import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import dirscan


class TestBytestringFuzz:
    """Fuzz tests for the bytestring() function."""

    @given(st.integers(min_value=0, max_value=10**15))
    def test_nonnegative_returns_string(self, amount):
        result = dirscan.bytestring(amount)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(st.integers(min_value=0, max_value=999))
    def test_bytes_range(self, amount):
        result = dirscan.bytestring(amount)
        assert "bytes" in result

    @given(st.integers(min_value=1000, max_value=999_999))
    def test_kib_range(self, amount):
        result = dirscan.bytestring(amount)
        assert "KiB" in result

    @given(st.integers(min_value=1_000_000, max_value=999_999_999))
    def test_mib_range(self, amount):
        result = dirscan.bytestring(amount)
        assert "MiB" in result

    @given(st.integers(min_value=1_000_000_000, max_value=999_999_999_999))
    def test_gib_range(self, amount):
        result = dirscan.bytestring(amount)
        assert "GiB" in result

    @given(st.integers(min_value=1_000_000_000_000, max_value=10**15))
    @settings(max_examples=50)
    def test_tib_range(self, amount):
        result = dirscan.bytestring(amount)
        assert "TiB" in result


class TestRunFuzz:
    """Fuzz tests for the run() function path handling."""

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=50)
    def test_dryrun_always_true(self, path):
        result = dirscan.run("echo", path, dryrun=True)
        assert result is True

    @given(st.text(min_size=1, max_size=100).filter(lambda x: "\0" not in x))
    @settings(max_examples=50)
    def test_path_with_special_chars(self, path):
        result = dirscan.run("echo %s", path, dryrun=True)
        assert result is True


class TestDirScannerFuzz:
    """Fuzz tests for DirScanner initialization and operation."""

    @given(
        st.sampled_from([True, False]),
        st.sampled_from([True, False]),
        st.sampled_from([True, False]),
        st.floats(min_value=-1.0, max_value=365.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=30)
    def test_creation_variants(self, check, sort, dryrun, days):
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = dirscan.DirScanner(
                directory=tmpdir,
                check=check,
                sort=sort,
                dryrun=dryrun,
                days=days,
            )
            assert scanner is not None

    def test_invalid_directory_rejected(self):
        with pytest.raises(dirscan.InvalidArgumentException):
            dirscan.DirScanner(directory="/nonexistent/path/fuzz_test")

    def test_none_directory_rejected(self):
        with pytest.raises(dirscan.InvalidArgumentException):
            dirscan.DirScanner(directory=None)


class TestEntryFuzz:
    """Fuzz tests for Entry creation and serialization."""

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=50)
    def test_str_returns_path(self, path):
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = dirscan.DirScanner(directory=tmpdir)
            entry = dirscan.Entry(scanner, path)
            assert str(entry) == path
            assert entry.path == path

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=50)
    def test_getstate_excludes_scanner(self, path):
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = dirscan.DirScanner(directory=tmpdir)
            entry = dirscan.Entry(scanner, path)
            state = entry.__getstate__()
            assert "_scanner" not in state
