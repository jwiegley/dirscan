# dirscan

I wrote this module because I needed to scan the same directories over and
over -- tracking what comes and goes, and doing something about it. My main
uses are cleaning up trash directories automatically and continuously
verifying the integrity of my file archives.

The idea is straightforward: `dirscan` remembers every file it's seen. On
each scan it figures out what's new, what's changed, and what's gone, then
calls your event handlers. State lives in a pickled database file, so it picks
up where it left off between runs. I've been running it daily on my systems
for years.

## Usage

From the command line:

```bash
python3 dirscan.py -d ~/Downloads -w 30 -v
```

This scans `~/Downloads`, flags anything older than 30 days, and prints
verbose output so you can see what's happening.

As a library, you subclass `Entry` and override the event hooks you care
about:

```python
import dirscan

class MyEntry(dirscan.Entry):
    def onEntryAdded(self):
        print(f"New: {self.path}")
        return True

    def onEntryRemoved(self):
        print(f"Gone: {self.path}")
        return True

scanner = dirscan.DirScanner(directory='/path/to/watch')
scanner.registerEntryClass(MyEntry)
scanner.scanEntries()
```

Returning `True` from a handler updates the state database; returning `False`
leaves it unchanged, so the event fires again on the next scan. This is handy
when an operation might fail and you want automatic retry.

## Events

- `onEntryAdded()` -- a file appears for the first time
- `onEntryChanged(contentsChanged)` -- metadata or content changed
- `onEntryRemoved()` -- a tracked file disappeared from disk
- `onEntryPastLimit(age)` -- a file exceeded the configured age limit

You can also pass shell commands as strings (with `%s` for the path) instead
of subclassing, if that's all you need.

## Checksum verification

For verifying archives against bit rot, there's a `--checksum-always` mode
with a check window:

```bash
python3 dirscan.py -d /archive --checksum-always --check-window=30
```

This re-checksums every file at least once a month, spreading the I/O
randomly so it doesn't try to verify everything at once. It's caught real
corruption for me more than once.

## Options

| Flag | Description |
|------|-------------|
| `-d DIR` | Directory to scan |
| `-w DAYS` | Age limit in days |
| `-v` | Verbose/debug output |
| `-n` | Dry run |
| `-R` / `--check` | Detect content changes via modtime |
| `--checksum` | Verify changes with SHA1 |
| `--checksum-always` | Periodic SHA1 regardless of modtime |
| `--check-window=N` | Re-checksum interval in days |
| `-z` | Minimal scan (only when directory mtime changes) |
| `-p` | Prune empty directories |
| `-s` | Retry failed operations with sudo |

## See also

- `cleanup` -- the script I use for automated trash cleanup across multiple
  volumes
- `verify.py` -- continuous file integrity verification using SHA1 and
  extended attributes
- `share.py` -- mirrors files between directories with ownership changes

## Development

```bash
nix develop          # enter dev shell with all dependencies
nix flake check      # run all checks (format, lint, tests, coverage, fuzz)
```

Or run tests directly:

```bash
python3 -m pytest test_dirscan.py -v
```

## License

BSD 3-Clause. See [LICENSE.md](LICENSE.md).
