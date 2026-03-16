#!/usr/bin/env python3
"""Performance benchmark tests for dirscan using pytest-benchmark."""

import os
import tempfile

import dirscan


def test_bytestring_bytes(benchmark):
    benchmark(dirscan.bytestring, 500)


def test_bytestring_mib(benchmark):
    benchmark(dirscan.bytestring, 5_000_000)


def test_bytestring_gib(benchmark):
    benchmark(dirscan.bytestring, 5_000_000_000)


def test_scanner_creation(benchmark):
    tmpdir = tempfile.mkdtemp()
    try:

        def create():
            return dirscan.DirScanner(directory=tmpdir)

        benchmark(create)
    finally:
        os.rmdir(tmpdir)


def test_scanner_scan_empty(benchmark):
    tmpdir = tempfile.mkdtemp()
    try:
        scanner = dirscan.DirScanner(directory=tmpdir)
        benchmark(scanner.scanEntries)
    finally:
        db = os.path.join(tmpdir, ".files.dat")
        if os.path.exists(db):
            os.remove(db)
        os.rmdir(tmpdir)


def test_scanner_scan_small(benchmark):
    tmpdir = tempfile.mkdtemp()
    try:
        for i in range(20):
            with open(os.path.join(tmpdir, f"file_{i}.txt"), "w") as f:
                f.write(f"content {i}\n")
        scanner = dirscan.DirScanner(directory=tmpdir, check=True)
        scanner.scanEntries()
        benchmark(scanner.scanEntries)
    finally:
        dirscan.deltree(tmpdir)


def test_entry_creation(benchmark):
    tmpdir = tempfile.mkdtemp()
    try:
        scanner = dirscan.DirScanner(directory=tmpdir)
        benchmark(dirscan.Entry, scanner, "/tmp/fake/path")
    finally:
        os.rmdir(tmpdir)
