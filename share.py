#!/usr/bin/env python3
# share.py - Mirror files from Nextcloud share to public share with ownership change
#
# Monitors /tank/Nextcloud/johnw/files/share for changes and mirrors them to
# /tank/Public/share, handling ownership changes from nextcloud:nextcloud to johnw:johnw.
# Uses checksum verification to detect content changes reliably.

import os
import sys
import getopt
import subprocess
import random
import logging as l

from dirscan import DirScanner, rightNow
from datetime import timedelta
from os.path import expanduser, join, dirname, exists, isdir, isfile
from typing import Optional

random.seed()

# Configuration
SOURCE_DIR = "/tank/Nextcloud/johnw/files/share"
DEST_DIR = "/tank/Public/share"
SOURCE_OWNER = "nextcloud:nextcloud"
DEST_OWNER = "johnw:johnw"
CHECK_WINDOW = 7  # Re-verify checksums every 7 days

# Global options
debug = False
opts = {
    'dryrun': False,
    'verbose': False
}


def ensure_dest_directory(dest_path: str) -> bool:
    """Ensure destination directory exists with proper ownership.

    Args:
        dest_path: Path to destination directory

    Returns:
        True if directory exists or was created successfully
    """
    if exists(dest_path):
        return True

    dest_dir = dirname(dest_path)
    if not exists(dest_dir):
        if not ensure_dest_directory(dest_dir):
            return False

    try:
        if not opts['dryrun']:
            os.makedirs(dest_path, exist_ok=True)
            # Set ownership to johnw:johnw
            subprocess.run(['chown', DEST_OWNER, dest_path], check=True)
            l.debug(f"Created directory: {dest_path}")
        else:
            l.debug(f"Would create directory: {dest_path}")
        return True
    except Exception as e:
        l.error(f"Failed to create directory {dest_path}: {e}")
        return False


def get_dest_path(source_path: str) -> str:
    """Convert source path to corresponding destination path.

    Args:
        source_path: Path in source directory

    Returns:
        Corresponding path in destination directory
    """
    # Remove SOURCE_DIR prefix and prepend DEST_DIR
    rel_path = os.path.relpath(source_path, SOURCE_DIR)
    return join(DEST_DIR, rel_path)


def copy_file_with_ownership(source_path: str, dest_path: str) -> bool:
    """Copy file and set proper ownership.

    Args:
        source_path: Source file path
        dest_path: Destination file path

    Returns:
        True if copy succeeded
    """
    try:
        # Ensure destination directory exists
        dest_dir = dirname(dest_path)
        if not ensure_dest_directory(dest_dir):
            return False

        if not opts['dryrun']:
            # Copy the file
            result = subprocess.run(
                ['cp', '-p', source_path, dest_path],
                check=True,
                capture_output=True,
                text=True
            )

            # Change ownership to johnw:johnw
            subprocess.run(
                ['chown', DEST_OWNER, dest_path],
                check=True,
                capture_output=True,
                text=True
            )

            l.debug(f"Copied {source_path} -> {dest_path}")
        else:
            l.debug(f"Would copy {source_path} -> {dest_path}")

        return True

    except subprocess.CalledProcessError as e:
        l.error(f"Failed to copy {source_path} to {dest_path}: {e}")
        if e.stderr:
            l.error(f"  stderr: {e.stderr}")
        return False
    except Exception as e:
        l.error(f"Unexpected error copying {source_path}: {e}")
        return False


def remove_file(dest_path: str) -> bool:
    """Remove file from destination.

    Args:
        dest_path: Destination file path to remove

    Returns:
        True if removal succeeded
    """
    try:
        if not exists(dest_path):
            l.debug(f"Destination already removed: {dest_path}")
            return True

        if not opts['dryrun']:
            result = subprocess.run(
                ['rm', '-f', dest_path],
                check=True,
                capture_output=True,
                text=True
            )
            l.debug(f"Removed {dest_path}")
        else:
            l.debug(f"Would remove {dest_path}")

        return True

    except subprocess.CalledProcessError as e:
        l.error(f"Failed to remove {dest_path}: {e}")
        if e.stderr:
            l.error(f"  stderr: {e.stderr}")
        return False
    except Exception as e:
        l.error(f"Unexpected error removing {dest_path}: {e}")
        return False


def on_file_added(entry) -> bool:
    """Handle new files detected in source directory.

    Args:
        entry: DirScanner Entry object for the new file

    Returns:
        True to track this entry in the database
    """
    # Skip directories - we only process files
    if entry.isDirectory():
        l.debug(f"Skipping directory: {entry.path}")
        return True

    dest_path = get_dest_path(entry.path)

    print(f"NEW: {entry.path}")
    l.info(f"  -> {dest_path}")

    # Copy file to destination with ownership change
    if copy_file_with_ownership(entry.path, dest_path):
        # Initialize checksum verification window (randomized to spread load)
        if CHECK_WINDOW:
            entry._lastCheck = rightNow - timedelta(random.randint(0, CHECK_WINDOW))
        return True
    else:
        l.error(f"Failed to copy new file: {entry.path}")
        return False


def on_file_changed(entry) -> bool:
    """Handle modified files detected in source directory.

    Args:
        entry: DirScanner Entry object for the changed file

    Returns:
        True to update the entry in the database
    """
    # Skip directories - we only process files
    if entry.isDirectory():
        return True

    dest_path = get_dest_path(entry.path)

    print(f"CHANGED: {entry.path}")
    l.info(f"  -> {dest_path}")

    # Re-copy file to destination
    if copy_file_with_ownership(entry.path, dest_path):
        return True
    else:
        l.error(f"Failed to update changed file: {entry.path}")
        return False


def on_file_removed(entry) -> bool:
    """Handle deleted files in source directory.

    Args:
        entry: DirScanner Entry object for the removed file

    Returns:
        True to remove the entry from the database
    """
    # Skip directories - we only process files
    if entry.isDirectory():
        return True

    dest_path = get_dest_path(entry.path)

    print(f"REMOVED: {entry.path}")
    l.info(f"  -> removing {dest_path}")

    # Remove corresponding file from destination
    if remove_file(dest_path):
        return True
    else:
        l.error(f"Failed to remove file: {dest_path}")
        return False


def main():
    """Main entry point for share.py."""
    global debug, opts

    args = None

    if len(sys.argv) > 1:
        try:
            options, args = getopt.getopt(sys.argv[1:], 'nvh', ['help'])
        except getopt.GetoptError as e:
            print(f"Error: {e}")
            print_usage()
            sys.exit(2)

        for o, a in options:
            if o in ('-v'):
                debug = True
                opts['verbose'] = True
                l.basicConfig(level=l.DEBUG,
                             format='[%(levelname)s] %(message)s')
            elif o in ('-n'):
                opts['dryrun'] = True
            elif o in ('-h', '--help'):
                print_usage()
                sys.exit(0)

    # If no explicit logging configured, use INFO level
    if not debug:
        l.basicConfig(level=l.INFO, format='%(message)s')

    # Verify source directory exists
    if not isdir(SOURCE_DIR):
        l.error(f"Source directory does not exist: {SOURCE_DIR}")
        sys.exit(1)

    # Ensure destination base directory exists
    if not exists(DEST_DIR):
        l.info(f"Creating destination directory: {DEST_DIR}")
        if not ensure_dest_directory(DEST_DIR):
            l.error(f"Failed to create destination directory: {DEST_DIR}")
            sys.exit(1)

    print(f"Monitoring: {SOURCE_DIR}")
    print(f"Mirroring to: {DEST_DIR}")
    print(f"Ownership: {SOURCE_OWNER} -> {DEST_OWNER}")

    if opts['dryrun']:
        print("DRY-RUN MODE: No actual changes will be made")

    # Create scanner with checksum verification
    scanner = DirScanner(
        directory=SOURCE_DIR,
        check=True,                    # Check for changes
        useChecksumAlways=True,        # Always verify with checksums
        checkWindow=CHECK_WINDOW,       # Re-verify every N days
        ignoreFiles=[
            r'^\.files\.dat$',         # Scanner database
            r'^\.DS_Store$',           # macOS metadata
            r'^\.localized$',          # macOS localization
            r'^Thumbs\.db$',           # Windows thumbnail cache
            r'^\.~lock\.',             # LibreOffice lock files
        ],
        onEntryAdded=on_file_added,
        onEntryChanged=on_file_changed,
        onEntryRemoved=on_file_removed,
        **opts
    )

    # Perform the scan
    scanner.scanEntries()

    print(f"\nScan complete.")


def print_usage():
    """Print usage information."""
    print("""
Usage: share.py [OPTIONS]

Mirror files from Nextcloud share to public share with ownership changes.

Options:
  -v            Verbose mode (debug logging)
  -n            Dry-run mode (no actual changes)
  -h, --help    Show this help message

Configuration:
  Source:      {SOURCE_DIR}
  Destination: {DEST_DIR}
  Ownership:   {SOURCE_OWNER} -> {DEST_OWNER}

The script uses checksum verification to reliably detect content changes
and will re-verify files every {CHECK_WINDOW} days to ensure integrity.
""".format(
        SOURCE_DIR=SOURCE_DIR,
        DEST_DIR=DEST_DIR,
        SOURCE_OWNER=SOURCE_OWNER,
        DEST_OWNER=DEST_OWNER,
        CHECK_WINDOW=CHECK_WINDOW
    ))


if __name__ == '__main__':
    main()

# share.py ends here
