# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`dirscan` is a Python 3.8+ library for stateful directory scanning - tracking files and directories over time and taking actions based on changes (additions, modifications, removals) or age limits. Designed for tasks like automated cleanup of trash directories and continuous file integrity verification.

**Note**: The code has been fully ported to Python 3.8+ with modern best practices. Header claims version 2.0, but `showVersion()` displays version 1.0.

## Python 3 Migration

This codebase was successfully migrated from Python 2.x to Python 3.8+ with the following changes:

### Core Language Changes
- **Module imports**: Changed `cPickle` to `pickle` (Python 3 unified these modules)
- **Integer types**: Removed `long()` type - all integers in Python 3 are arbitrary precision
  - Changed `long(value)` to `int(value)` throughout
  - Removed `0L` suffix from integer literals
- **Dictionary methods**: Replaced `.has_key()` with `in` operator (9 occurrences)
- **Exception syntax**: Updated `except Exception, e:` to `except Exception as e:`
- **Print statements**: Converted to `print()` function calls
- **String formatting**: Migrated from `%` formatting to f-strings for clarity and performance
- **Integer division**: Updated division operators for Python 3's true division semantics

### Modern Python Features Added
- **Type hints**: Added type annotations to key functions and methods using `typing` module
  - Function signatures now include parameter and return types
  - Optional types used where appropriate
- **F-strings**: Used throughout for more readable string formatting
- **Raw strings**: Added `r` prefix to regex patterns to avoid escape sequence warnings
- **List comprehensions**: Used `list()` wrapper for dict.keys() where modification occurs during iteration

### API Compatibility
- **100% backward compatible** with existing `.files.dat` state databases
- All public APIs remain unchanged - existing user code will continue to work
- State file format unchanged - can read databases created by Python 2 version
- Includes upgrade mechanism for legacy state database formats

### Requirements
- **Minimum Python version**: 3.8+ (required for modern type hint syntax with `=`)
- All dependencies are standard library modules (no external packages needed)

## Core Architecture

### Key Classes

**`Entry`** (/Users/johnw/src/dirscan/dirscan.py:85-442)
- Represents a file or directory being tracked
- Maintains timestamps, checksums (SHA1), and metadata
- Provides event hooks: `onEntryAdded`, `onEntryChanged`, `onEntryRemoved`, `onEntryPastLimit`
- Supports custom subclassing to override behavior via `registerEntryClass()`
- Implements custom pickle serialization via `__getstate__` and `__setstate__`
  - Deliberately excludes `_scanner` reference from pickled state (line 436)
  - Preserves `_prevStamp` and `_prevInfo` for change detection across runs

**`DirScanner`** (/Users/johnw/src/dirscan/dirscan.py:455-1046)
- Main orchestrator that scans directories and maintains persistent state
- Stores state in a pickled database file (default: `.files.dat`)
- Uses file locking (`fcntl.flock`) for safe concurrent access:
  - Shared lock (`LOCK_SH`) when loading state (line 590)
  - Exclusive lock (`LOCK_EX`) when saving state (line 647)
  - Locks released in finally blocks for safety
- Supports both full directory walks and minimal scans (only when directory mtime changes)
- Factory pattern: `createEntry()` creates Entry instances, customizable via `registerEntryClass()`

### State Management Pattern

The scanner uses a "shadow dictionary" pattern during scans:
1. Copy current entries to `_shadow` dictionary (line 968)
2. Walk the directory tree, removing entries from `_shadow` as they're encountered (line 707)
3. Any entries remaining in `_shadow` after scan have been deleted from disk (line 985)
4. State is persisted to database using `cPickle` with exclusive file locking

**Backward Compatibility**: The scanner includes an upgrade mechanism (lines 599-610) to convert state databases created by the older cleanup.py script format (which stored raw datetime objects instead of Entry objects).

**Large Scan Optimization**: For very large directories, the scanner periodically saves state every 10GB of checksummed data (lines 826-829) to prevent data loss on long-running scans. Uses temporary database mechanism for atomic updates.

### Event-Driven Architecture

The system is callback-based. Event handlers can be:
- **String commands**: Shell commands with `%s` placeholder for path (e.g., `"mv %s /archive"`)
- **Callable objects**: Python functions that receive an `Entry` object

Event handlers return `True` to update state, `False` to prevent state changes. Returning `False` from `onEntryAdded` prevents the entry from being tracked. Event handlers are called even for files that no longer exist (for removal events).

## Code Style Notes

### String Formatting
- Modern f-strings used throughout for clarity and performance
- Shell escaping in `run()` function uses raw strings: `re.sub(r"([$\"\\])", r"\\\1", path)`

### Type Hints
Key functions include type annotations:
- `run(cmd: str, path: str, dryrun: bool = False) -> bool`
- `Entry.size` property returns `int`
- `Entry.checksum` property returns `Optional[str]`
- `Entry.onEntryAdded()`, `onEntryChanged()`, `onEntryRemoved()` return `bool`
- `Entry.onEntryPastLimit(age: float) -> None`
- `DirScanner.saveState(tempDirectory: Optional[str] = None) -> None`
- `bytestring(amount: int) -> str`

### Backward Compatibility Notes
The pickle-based state database format is fully compatible between Python 2 and Python 3. When loading a state database created by the Python 2 version, the code automatically handles the format and upgrades legacy datetime-only entries to full Entry objects.

## Testing

Run tests with Python 3:
```bash
python3 test_dirscan.py
```

Or run with verbose output:
```bash
python3 test_dirscan.py -v
```

Tests create temporary directories under `/tmp/DirScannerTest` and verify:
- File addition/change/removal detection
- Event handler success/failure paths
- State persistence across scans
- Custom Entry subclass demonstrates pattern for extending behavior (lines 14-40)

All 7 tests pass successfully with Python 3.8+.

## Common Usage Patterns

### Command-line Usage

Run the module directly with Python 3:
```bash
python3 dirscan.py -d ~/MyDirectory -w 7 -v
```

Key options:
- `-d DIR` / `--dir=DIR`: Directory to scan
- `-w DAYS` / `--days=DAYS`: Age limit before triggering `onEntryPastLimit`
- `-v` / `--verbose`: Debug logging
- `-n` / `--nothing`: Dry-run mode (no changes)
- `-R` / `--check`: Check for content changes using modtime
- `--checksum`: Verify content changes with SHA1
- `--checksum-always`: Always verify with SHA1 regardless of mtime
- `--check-window=N`: Only re-checksum every N days (with `--checksum-always`)
- `-z` / `--minimal-scan`: Only scan when directory modtime changes
- `-p` / `--prune-dirs`: Remove empty directories
- `-s` / `--sudo`: Retry failed operations with sudo

**Note**: There's a bug at line 1222 where `options['database']` is set to the days value instead of the database value.

### Library Usage

Two example scripts demonstrate library usage:

**cleanup** (170 lines) - Automated trash cleanup across multiple volumes
- Scans trash directories with 28-day age limits
- Enforces size limits (1-2% of volume capacity)
- Uses `minimalScan` for efficiency
- Demonstrates hardcoded paths specific to the author's macOS system

**verify.py** (94 lines) - File integrity verification
- Computes and stores SHA1 checksums using extended attributes (`xattr`)
- Periodically re-verifies file contents (configurable window)
- Logs changes/removals to `~/Desktop/verify.log`
- Demonstrates custom `onEntryAdded` handler and checksum integration
- Uses macOS-specific `xattr -p checksum-sha1` command

### Custom Entry Subclasses

To extend behavior, create a custom Entry class and register it:

```python
class MyEntry(dirscan.Entry):
    def onEntryAdded(self):
        # Custom logic
        return True  # or False to prevent tracking

scanner = dirscan.DirScanner(directory='/path/to/dir')
scanner.registerEntryClass(MyEntry)
scanner.scanEntries()
```

The `test_dirscan.py` file provides a complete example (lines 14-40).

## Important Implementation Details

### Checksum Verification

When `useChecksumAlways=True` with `checkWindow=N`:
- Files are checksummed on first encounter
- Re-checksummed every N days (randomized to spread load)
- `_lastCheck` timestamp tracks last verification (lines 197-199)
- Random offset prevents all files from being rechecked simultaneously
- Checksumming triggers `_dirty` flag to ensure state is saved (line 201)
- `_bytesScanned` counter tracks total data processed (line 190)
- Useful for detecting bit rot in archival storage

The `contentsHaveChanged()` method (lines 206-240) implements sophisticated logic:
- If `useChecksum=True`: Only checksums when mtime changes
- If `useChecksumAlways=True`: Checksums periodically regardless of mtime
- Respects `checkWindow` to avoid excessive I/O

### Attribute Caching

The `cacheAttrs` option controls whether file attributes are cached:
- When `True`: `os.lstat()` results are cached in `_info`
- When `False`: Attributes are re-read on each access (lines 138-139, 149-150, 165-166)
- Cache is explicitly cleared when `_scanner.cacheAttrs` is False
- All property accessors that use `_info` check this flag

This is critical for:
- Long-running scans where files might change during the scan
- Ensuring accurate timestamps and sizes when `check=True`

### Entry Iteration

Use `walkEntries()` to iterate over all tracked entries (lines 756-760):

```python
def processEntry(entry):
    print entry.path, entry.size

scanner.walkEntries(processEntry)
```

### Size Computation

The `computeSizes()` method (lines 762-775) builds a reverse index:
- Maps size -> list of entries
- Used for size-based cleanup (largest files first)
- Directory sizes are computed recursively via `Entry.size` property
- Returns tuple: `(total_size, size_map)`

### Timestamp Management

Entry timestamps can come from three sources:
1. `atime=True`: Use file's last access time (line 243)
2. `mtime=True`: Use file's last modification time (line 245)
3. Neither: Use `_stamp` - when file was first seen (line 249)

The `timestamp` property (line 258) abstracts this, allowing consistent age calculations.

### Removal Behavior

The `Entry.remove()` method (lines 318-385) is sophisticated:
- Handles files, symlinks, and directories differently
- Optionally uses secure deletion (`/bin/srm -f`) when `secure=True`
- Falls back to sudo if initial removal fails
- Uses custom `deltree()` for fast directory deletion (delegates to `/bin/rm -fr`)
- Always checks if file still exists after deletion attempt
- Logs errors but doesn't raise exceptions (for resilience)

### State Database Versioning

The loader (lines 599-610) handles legacy format:
- Old format: `{path: datetime_stamp, ...}`
- New format: `{path: Entry_object, ...}`
- Automatically upgrades on load
- Ensures all loaded entries have `_scanner` reference set

## Deployment

The included `com.newartisans.cleanup.plist` is a macOS launchd configuration that runs the cleanup script daily at 6:00 PM using sudo.

## Potential Issues & Gotchas

### Concurrency
- File locking prevents multiple simultaneous scans of the same directory
- But no protection against the directory being modified during scan
- Long scans might see inconsistent snapshots

### Memory Usage
- All entries kept in memory (`_entries` dict)
- For directories with millions of files, this could be problematic
- No streaming or pagination support

### Minimal Scan Behavior
When `minimalScan=True`:
- Compares database mtime with directory mtime
- If directory unchanged: **Skips filesystem walk** but **still processes all database entries**
- This allows age-based cleanup to work even when no files were added/removed
- Example: A file that was 27 days old yesterday is 28 days old today, even if directory mtime unchanged

**Limitations:**
- Only checks top-level directory mtime, not subdirectory mtimes
- Warning logged if used with `depth != 0` (line 534)
- Files added/removed in subdirectories won't be detected if parent dir mtime unchanged
- Not a true "skip everything" optimization - still iterates through all database entries

### Platform Dependencies
- File locking uses `fcntl` module (Unix-only)
- Trash location hardcoded to `~/.Trash` (macOS convention)
- Extended attributes in verify.py are macOS-specific
- Secure deletion uses `/bin/srm` (not available on all systems)

### Error Handling
- Many operations silently catch exceptions and log errors
- Failed deletions don't stop the scan
- Database corruption during write is partially handled (line 652: deletes partial file)
