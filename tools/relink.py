#!/usr/bin/env python3
"""
Link an already-published page that is missing from the site's indexes.

For pages that exist under w/ but have no card in index.html and no feed or
sitemap entry, so nothing links to them. Reads the page itself rather than a
JSON description, and adds only what is missing.

Usage:
    python3 tools/relink.py <slug> [--dry-run]
"""

import argparse
import html as htmllib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import (  # noqa: E402
    ROOT, parse_index, read, write, esc, build_card, update_filters,
    update_feed, update_sitemap,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    slug = a.slug.removesuffix(".html").removeprefix("w/")
    url = f"/w/{slug}.html"
    path = os.path.join(ROOT, "w", f"{slug}.html")
    if not os.path.exists(path):
        sys.exit(f"error: no such page: w/{slug}.html")

    s = read(path)
    title = htmllib.unescape(re.sub(r"<[^>]+>", "", re.search(r'<h1 class="t">(.*?)</h1>', s, re.S).group(1))).strip()
    date = re.search(r"</span>\s*(\d{4}-\d{2}-\d{2})", s).group(1)
    theme = htmllib.unescape(re.search(r'<span class="tag">(.*?)</span>', s).group(1)).strip()
    him = re.search(r'<img class="hero-img" src="/img/([^"]+)"', s)

    body = re.search(r'<div class="body">(.*?)</div>', s, re.S)
    first = re.search(r"<p>(.*?)</p>", body.group(1), re.S) if body else None
    excerpt = htmllib.unescape(re.sub(r"<[^>]+>", "", first.group(1))).strip() if first else title
    if len(excerpt) > 300:
        excerpt = excerpt[:300].rsplit(" ", 1)[0]

    p = {
        "url": url, "title": title, "date": date, "theme": theme,
        "excerpt": excerpt, "image_name": him.group(1) if him else None,
    }

    index = read(os.path.join(ROOT, "index.html"))
    prefix, cards, suffix = parse_index(index)
    if any(c["url"] == url for c in cards):
        sys.exit(f"error: {url} already has a card in index.html")

    def key(c):
        if c["date"]:
            return c["date"]
        m = re.search(r'data-date="([0-9-]+)"', c["raw"])
        return m.group(1) if m else ""

    card = {**p, "raw": build_card(p), "date": date}
    pos = next((i for i, c in enumerate(cards) if key(c) < date), len(cards))
    new_cards = cards[:pos] + [card] + cards[pos:]
    new_index = update_filters(prefix + "".join(c["raw"] for c in new_cards) + suffix, theme)

    feed, feed_ok = update_feed(read(os.path.join(ROOT, "feed.xml")), p)
    sm, sm_ok = update_sitemap(read(os.path.join(ROOT, "sitemap.xml")), p)

    print(f"  title     {title}")
    print(f"  index     card #{pos + 1} of {len(new_cards)}  [{theme}] {date}")
    print(f"  image     {p['image_name'] or 'none'}")
    print(f"  feed.xml  {'added' if feed_ok else 'already present'}")
    print(f"  sitemap   {'added' if sm_ok else 'already present'}")

    if a.dry_run:
        print("\ndry run — nothing written")
        return

    write(os.path.join(ROOT, "index.html"), new_index)
    write(os.path.join(ROOT, "feed.xml"), feed)
    write(os.path.join(ROOT, "sitemap.xml"), sm)
    print(f"\nlinked {url}")


if __name__ == "__main__":
    main()
