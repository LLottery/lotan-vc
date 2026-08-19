#!/usr/bin/env python3
"""
Ingest a whole LinkedIn export bundle in one step.

Takes the zip produced by tools/linkedin-export-prompt.md, extracts it, and
runs every post it contains through ingest.py in chronological order, so the
writing list ends up correctly ordered.

Usage:
    python3 tools/ingest-zip.py linkedin-export.zip            # apply
    python3 tools/ingest-zip.py linkedin-export.zip --dry-run  # preview
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ingest even if verification reports errors")
    a = ap.parse_args()

    if not zipfile.is_zipfile(a.zip):
        sys.exit(f"error: not a zip file: {a.zip}")

    # Verify before writing anything. A mis-paired post looks structurally
    # perfect once published, so the cheap moment to catch it is now.
    print("verifying bundle...\n")
    v = subprocess.run(
        [sys.executable, os.path.join(HERE, "verify-bundle.py"), a.zip],
        capture_output=True, text=True,
    )
    sys.stdout.write(v.stdout)
    if v.returncode and not a.force:
        sys.exit("\nverification failed — fix the bundle, or re-run with --force")
    if v.returncode:
        print("\nverification failed, continuing because --force was given\n")
    print("-" * 60 + "\n")

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(a.zip) as z:
            # Refuse paths that would escape the extraction directory.
            for n in z.namelist():
                if os.path.isabs(n) or ".." in os.path.normpath(n).split(os.sep):
                    sys.exit(f"error: unsafe path in zip: {n}")
            z.extractall(tmp)

        posts = sorted(glob.glob(os.path.join(tmp, "**", "*.json"), recursive=True))
        if not posts:
            sys.exit("error: no .json posts found in the zip")

        # Oldest first, so each new card is inserted above the previous one.
        def when(f):
            try:
                return json.load(open(f, encoding="utf-8")).get("date", "")
            except Exception:
                return ""

        posts.sort(key=when)

        print(f"{len(posts)} post(s) in {os.path.basename(a.zip)}\n")

        flagged, failed, done = [], [], 0
        for f in posts:
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception as e:
                failed.append((os.path.basename(f), f"unreadable JSON: {e}"))
                continue

            if d.get("english_is_machine_translation"):
                flagged.append((d.get("date", "?"), d.get("title", "?")))
                print(f"— skipping {d.get('date','?')}  {d.get('title','?')}")
                print("  English is a machine translation; needs approval first")
                continue

            print(f"— {d.get('date','?')}  {d.get('title','?')}")
            cmd = [sys.executable, os.path.join(HERE, "ingest.py"), f]
            if a.dry_run:
                cmd.append("--dry-run")
            r = subprocess.run(cmd, capture_output=True, text=True)
            sys.stdout.write(r.stdout)
            if r.returncode:
                failed.append((os.path.basename(f), r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "failed"))
                sys.stdout.write(r.stderr)
            else:
                done += 1
            print()

        print(f"{'would ingest' if a.dry_run else 'ingested'}: {done}")
        if flagged:
            print(f"held for translation approval: {len(flagged)}")
            for d, t in flagged:
                print(f"  {d}  {t}")
        if failed:
            print(f"failed: {len(failed)}")
            for n, why in failed:
                print(f"  {n}: {why}")
            sys.exit(1)


if __name__ == "__main__":
    main()
