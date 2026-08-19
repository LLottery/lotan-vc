#!/usr/bin/env python3
"""
Remove a published post from lotan.vc.

Undoes everything ingest.py does: deletes the page and its images, removes the
card from index.html, decrements the filter counts, and drops the feed.xml and
sitemap.xml entries.

Usage:
    python3 tools/unpublish.py <slug> [--dry-run]
"""

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import ROOT, parse_index, read, write, esc, activity_id  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    slug = a.slug.removesuffix(".html").removeprefix("w/")
    url = f"/w/{slug}.html"
    page = os.path.join(ROOT, "w", f"{slug}.html")
    if not os.path.exists(page):
        sys.exit(f"error: no such post: w/{slug}.html")

    html = read(page)
    aid = activity_id(re.search(r"urn:li:activity:\d+", html).group(0)) if "urn:li:activity:" in html else None

    index = read(os.path.join(ROOT, "index.html"))
    prefix, cards, suffix = parse_index(index)
    keep = [c for c in cards if c["url"] != url]
    gone = [c for c in cards if c["url"] == url]
    if not gone:
        print(f"note: no card for {url} in index.html")
    theme = gone[0]["theme"] if gone else None

    new_index = prefix + "".join(c["raw"] for c in keep) + suffix

    def drop(m):
        return f"{m.group(1)}({int(m.group(2)) - 1})"

    if gone:
        aside = re.search(r'<aside class="filters">.*?</aside>', new_index, re.S)
        if aside:
            block = aside.group(0)
            nb = re.sub(r"(>All )\((\d+)\)", drop, block, count=1)
            pat = r"(>" + re.escape(esc(theme)) + r" )\((\d+)\)"
            if re.search(pat, nb):
                nb = re.sub(pat, drop, nb, count=1)
            new_index = new_index.replace(block, nb, 1)

    feed = read(os.path.join(ROOT, "feed.xml"))
    new_feed = re.sub(r"<item>(?:(?!</item>).)*?" + re.escape(url) + r".*?</item>\n?", "", feed, flags=re.S)
    sm = read(os.path.join(ROOT, "sitemap.xml"))
    new_sm = re.sub(r"<url><loc>https://lotan\.vc" + re.escape(url) + r"</loc></url>\n?", "", sm)

    images = sorted(glob.glob(os.path.join(ROOT, "img", f"{aid}*"))) if aid else []

    print(f"  page      w/{slug}.html")
    print(f"  index     card removed ({len(cards)} -> {len(keep)})" + (f"  [{theme}]" if theme else ""))
    print(f"  feed.xml  {'entry removed' if new_feed != feed else 'no entry'}")
    print(f"  sitemap   {'entry removed' if new_sm != sm else 'no entry'}")
    for i in images:
        print(f"  image     {os.path.basename(i)}")

    if a.dry_run:
        print("\ndry run — nothing removed")
        return

    os.remove(page)
    for i in images:
        os.remove(i)
    write(os.path.join(ROOT, "index.html"), new_index)
    write(os.path.join(ROOT, "feed.xml"), new_feed)
    write(os.path.join(ROOT, "sitemap.xml"), new_sm)
    print(f"\nremoved {url}")


if __name__ == "__main__":
    main()
