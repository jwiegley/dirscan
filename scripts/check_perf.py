#!/usr/bin/env python3
"""Compare current benchmark results against stored baseline.

Fails if any benchmark regresses by more than 5% AND the absolute difference
exceeds 1ms. This avoids false positives from sub-millisecond benchmarks where
tiny absolute variations produce large percentage swings.

Run with --update-baseline to regenerate the baseline file.
"""

import json
import os
import subprocess
import sys
import tempfile

BASELINE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".perf-baseline.json")
REGRESSION_THRESHOLD_PCT = 5  # percentage change to flag
REGRESSION_THRESHOLD_ABS = 0.001  # minimum absolute difference in seconds (1ms)


def run_benchmarks():
    """Run benchmarks and return results as dict."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "test_perf.py",
                "-x",
                "-q",
                f"--benchmark-json={tmp_path}",
                "--benchmark-disable-gc",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Benchmark run failed:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        with open(tmp_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def extract_timings(data):
    """Extract benchmark name -> median time mapping."""
    return {b["name"]: b["stats"]["median"] for b in data["benchmarks"]}


def main():
    update = "--update-baseline" in sys.argv

    current_data = run_benchmarks()
    current = extract_timings(current_data)

    if update or not os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE, "w") as f:
            json.dump(current_data, f, indent=2)
        print(f"Baseline {'updated' if update else 'created'}: {BASELINE_FILE}")
        for name, time in sorted(current.items()):
            print(f"  {name}: {time:.6f}s")
        return

    with open(BASELINE_FILE) as f:
        baseline_data = json.load(f)
    baseline = extract_timings(baseline_data)

    regressions = []
    for name, current_time in sorted(current.items()):
        if name in baseline:
            baseline_time = baseline[name]
            if baseline_time > 0:
                change = (current_time - baseline_time) / baseline_time * 100
                abs_diff = current_time - baseline_time
                is_regression = (
                    change > REGRESSION_THRESHOLD_PCT and abs_diff > REGRESSION_THRESHOLD_ABS
                )
                status = "REGRESSION" if is_regression else "ok"
                print(
                    f"  {name}: {current_time:.6f}s "
                    f"(baseline {baseline_time:.6f}s, {change:+.1f}%) [{status}]"
                )
                if is_regression:
                    regressions.append((name, change))
        else:
            print(f"  {name}: {current_time:.6f}s (new, no baseline)")

    if regressions:
        print(
            f"\nFAILED: {len(regressions)} benchmark(s) regressed by more than "
            f"{REGRESSION_THRESHOLD_PCT}% (with >{REGRESSION_THRESHOLD_ABS * 1000:.0f}ms absolute change):"
        )
        for name, change in regressions:
            print(f"  {name}: {change:+.1f}%")
        sys.exit(1)
    else:
        print("\nAll benchmarks within tolerance.")


if __name__ == "__main__":
    main()
