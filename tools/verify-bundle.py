#!/usr/bin/env python3
"""
Check an export bundle before anything is published.

A mis-paired post — one post's text carrying another post's activity id — passes
every structural test, because the date, the image name and the provenance link
are all derived from that same wrong id. It only shows up when you open the
image. This checks what can be checked mechanically and names what still needs
eyes.

Usage:
    python3 tools/verify-bundle.py linkedin-export.zip
    python3 tools/verify-bundle.py <directory>
    python3 tools/verify-bundle.py <bundle> --review    # manifest for eyeballing
"""

import argparse
import collections
import datetime
import glob
import json
import os
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import ROOT, activity_id, read  # noqa: E402

THEMES = {
    "AI Market Structure", "Service as Software", "Founder-Investor Dynamics",
    "Founder Validation", "Data Moats", "Where to Build", "Why We Invested",
    "AI and Work", "Investing Posture", "Founder Patterns", "SaaS under AI",
    "Company Formation", "GTM Data Layer", "Building AI Products",
    "Enterprise AI", "Frameworks",
}
MAX_GAP_DAYS = 14  # posts weekly; a fortnight of silence is more likely a miss


def id_date(aid):
    return datetime.datetime.utcfromtimestamp((int(aid) >> 22) / 1000).strftime("%Y-%m-%d")


def published():
    """activity id -> page, for everything already on the site."""
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "w", "*.html"))):
        m = re.search(r"urn:li:activity:(\d+)", read(f))
        if m:
            out[m.group(1)] = os.path.basename(f)
    return out


def load(bundle):
    """Return (directory, [(path, dict)]) for a zip or a directory."""
    tmp = None
    if os.path.isdir(bundle):
        root = bundle
    else:
        if not zipfile.is_zipfile(bundle):
            sys.exit(f"error: not a zip or directory: {bundle}")
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(bundle) as z:
            for n in z.namelist():
                if os.path.isabs(n) or ".." in os.path.normpath(n).split(os.sep):
                    sys.exit(f"error: unsafe path in zip: {n}")
            z.extractall(tmp.name)
        root = tmp.name

    posts = []
    for f in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
        try:
            posts.append((f, json.load(open(f, encoding="utf-8"))))
        except Exception as e:
            posts.append((f, {"__error__": str(e)}))
    return tmp, root, posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--review", action="store_true", help="print a manifest for visual checking")
    a = ap.parse_args()

    tmp, root, posts = load(a.bundle)
    if not posts:
        sys.exit("error: no .json posts found")

    live = published()
    errors, warnings = [], []
    seen_ids, seen_slugs, seen_images = {}, {}, {}
    dated = []

    for path, d in posts:
        name = os.path.basename(path)
        if "__error__" in d:
            errors.append(f"{name}: unreadable JSON — {d['__error__']}")
            continue

        for k in ("title", "date", "theme", "body_en", "linkedin_url"):
            if not d.get(k):
                errors.append(f"{name}: missing required field '{k}'")

        aid = activity_id(d.get("linkedin_url", ""))
        if not aid:
            errors.append(f"{name}: linkedin_url has no activity id")
        else:
            if aid in seen_ids:
                errors.append(f"{name}: activity {aid} also in {seen_ids[aid]}")
            seen_ids[aid] = name

            if aid in live:
                warnings.append(f"{name}: activity {aid} already published as w/{live[aid]} — will be skipped")

            if d.get("date"):
                want = id_date(aid)
                if d["date"] != want:
                    errors.append(f"{name}: date {d['date']} but activity id says {want}")
                dated.append((d["date"], name, d.get("title", "")))

            # the witness is captured beside the id at collection time, so a
            # shuffle between text and id shows up here
            w = (d.get("text_witness") or "").strip()
            if w:
                body = (d.get("body_he") or d.get("body_en") or "").strip()
                if not body.startswith(w[:40]):
                    errors.append(
                        f"{name}: text_witness does not match the body — "
                        f"text and activity id may belong to different posts"
                    )
            else:
                warnings.append(f"{name}: no text_witness, pairing cannot be checked mechanically")

        if d.get("theme") and d["theme"] not in THEMES:
            warnings.append(f"{name}: unfamiliar theme {d['theme']!r}")

        slug = re.sub(r"[^a-z0-9]+", "-", (d.get("title") or "").lower()).strip("-")
        if slug and slug in seen_slugs:
            errors.append(f"{name}: title collides with {seen_slugs[slug]}")
        seen_slugs[slug] = name

        for key, val in (("image", d.get("image")), *[("figure", f if isinstance(f, str) else f.get("file")) for f in (d.get("figures") or [])]):
            if not val:
                continue
            p = val if os.path.isabs(val) else os.path.join(os.path.dirname(path), val)
            if not os.path.exists(p):
                errors.append(f"{name}: {key} file not found: {val}")
            else:
                base = os.path.basename(val)
                if base in seen_images and seen_images[base] != name:
                    errors.append(f"{name}: image {base} also used by {seen_images[base]}")
                seen_images[base] = name
                if aid and not base.startswith(aid):
                    warnings.append(f"{name}: image {base} is not named for activity {aid}")

        if not d.get("image"):
            warnings.append(f"{name}: no image")
        if d.get("english_is_machine_translation"):
            warnings.append(f"{name}: machine translation, will be held back")

    # coverage: gaps against bundle + site combined
    all_dates = sorted({dt for dt, _, _ in dated} | {
        id_date(i) for i in live if i.isdigit()
    })
    gaps = []
    for x, y in zip(all_dates, all_dates[1:]):
        dx, dy = (datetime.date.fromisoformat(v) for v in (x, y))
        if (dy - dx).days > MAX_GAP_DAYS:
            gaps.append(((dy - dx).days, x, y))

    print(f"bundle: {len(posts)} post(s)")
    if dated:
        print(f"range:  {min(d for d, _, _ in dated)} .. {max(d for d, _, _ in dated)}")
    print()

    if errors:
        print(f"ERRORS ({len(errors)}) — do not ingest until resolved")
        for e in errors:
            print("  ✗", e)
        print()
    if warnings:
        print(f"WARNINGS ({len(warnings)})")
        for w in warnings:
            print("  !", w)
        print()
    if gaps:
        print(f"COVERAGE — {len(gaps)} gap(s) over {MAX_GAP_DAYS} days, counting posts already on the site")
        for g, x, y in sorted(gaps, reverse=True)[:15]:
            print(f"  {g:>4} days between {x} and {y}")
        print()

    if a.review:
        print("REVIEW MANIFEST — open each image and confirm it belongs to its post")
        for path, d in sorted(posts, key=lambda p: p[1].get("date", "")):
            if "__error__" in d:
                continue
            first = (d.get("body_en") or "").strip().split("\n")[0][:72]
            print(f"\n  {d.get('date','?')}  {d.get('title','?')}")
            print(f"    image: {d.get('image','none')}")
            print(f"    opens: {first}")
        print()

    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    if tmp:
        tmp.cleanup()
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
