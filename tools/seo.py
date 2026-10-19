#!/usr/bin/env python3
"""
Shared SEO/GEO helpers for lotan.vc, and a refresh entry point.

ingest.py calls these so a newly published post gets the same tags, author
identity, description trimming, essay canonical, sitemap lastmod, and index
pages as the rest of the site. Running this file refreshes pages already on
disk:

    python3 tools/seo.py           # apply
    python3 tools/seo.py --check   # validate, write nothing
"""

import glob
import html as htmllib
import json
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SITE = "https://lotan.vc"
SITE_NAME = "Lotan Levkowitz"
PORTRAIT = f"{SITE}/img/portrait.jpg"
META_LIMIT = 155
ELLIPSIS = "…"

# LinkedIn keeps the trailing slash already used on the site. worksFor still
# points at the Grove homepage; sameAs uses the team profile instead.
SAME_AS = [
    "https://www.linkedin.com/in/lotanlevkowitz/",
    "https://x.com/lotanlev",
    "https://www.grovevc.com/team/lotan-levkowitz/",
    "https://lotanl.substack.com",
]
KNOWS_ABOUT = [
    "enterprise AI",
    "data moats",
    "service-as-software",
    "venture capital",
    "Israeli tech",
]

ESSAY_INDEX_TITLE = "Essays — Lotan Levkowitz"
ESSAY_INDEX_DESC = (
    "Essays by Lotan Levkowitz on enterprise AI, data moats, "
    "service-as-software, and company formation."
)
NOTES_INDEX_TITLE = "Field notes — Lotan Levkowitz"
NOTES_INDEX_DESC = (
    "Field notes by Lotan Levkowitz, archived from LinkedIn, on enterprise AI, "
    "data moats, and company formation."
)

CSP = (
    "default-src 'self'; script-src 'self' https://gc.zgo.at 'unsafe-inline'; "
    "connect-src https://lotanvc2.goatcounter.com; img-src 'self' "
    "https://lotanvc2.goatcounter.com; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self' mailto:"
)


def esc(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_if_changed(path, text):
    if os.path.exists(path) and read(path) == text:
        return False
    write(path, text)
    return True


def norm_ws(text):
    return re.sub(r"\s+", " ", text or "").strip()


def norm_title(title):
    title = htmllib.unescape(title or "").casefold()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def meta_description(text, limit=META_LIMIT):
    """Cut on a word boundary. Longer text ends with an ellipsis within `limit`."""
    text = norm_ws(text)
    if len(text) <= limit:
        return text
    budget = limit - len(ELLIPSIS)
    cut = text[:budget]
    if not text[budget].isspace():
        sp = cut.rfind(" ")
        if sp > 0:
            cut = cut[:sp]
    cut = cut.rstrip(" \t,;:-–—")
    return cut + ELLIPSIS


def _without_ellipsis(text):
    text = norm_ws(text)
    if text.endswith(ELLIPSIS):
        return text[: -len(ELLIPSIS)].rstrip()
    if text.endswith("..."):
        return text[:-3].rstrip()
    return text


def is_extension_of(short, long):
    """True when `long` is the same text `short` was sliced from."""
    short, long = norm_ws(short), norm_ws(long)
    if not short or not long or len(long) <= len(_without_ellipsis(short)):
        return False
    stem = _without_ellipsis(short)
    if long.startswith(stem):
        return True
    if " " not in stem:
        return False
    head, partial = stem.rsplit(" ", 1)
    if not long.startswith(head + " "):
        return False
    nxt = long[len(head):].lstrip().split(" ", 1)[0]
    return nxt.startswith(partial)


def repair_hard_cut(text, limit=META_LIMIT):
    """A description already sliced at `limit`, with no longer source available."""
    text = norm_ws(text)
    if text.endswith((ELLIPSIS, "...", ".", "!", "?")) and len(text) <= limit:
        return text
    if text and text[-1].isalnum():
        # The slice landed inside a word. Drop that fragment.
        if " " in text:
            text = text.rsplit(" ", 1)[0]
        # And a one-to-three letter word left starting the next sentence.
        text = re.sub(r"(?<=[.!?])\s+\w{1,3}$", "", text)
    text = text.rstrip(" \t,;:-–—")
    if len(text) + len(ELLIPSIS) <= limit:
        return text + ELLIPSIS
    return meta_description(text)


def best_source(current, candidates):
    current_n = norm_ws(current)
    best = current_n
    for cand in candidates:
        cand_n = norm_ws(cand)
        if len(cand_n) > len(best) and is_extension_of(best, cand_n):
            best = cand_n
    return best


def descriptions_for(meta, candidates):
    """Return (meta_description, jsonld_description)."""
    meta_n = norm_ws(meta)
    source = best_source(meta_n, candidates)
    if len(source) > META_LIMIT:
        return meta_description(source), source
    if meta_n.endswith(ELLIPSIS) or meta_n.endswith((".", "!", "?")):
        full = source if len(source) >= len(meta_n) else meta_n
        return meta_n, full
    # Stored excerpt[:155] (or a trailing space trimmed off that slice).
    if len(meta_n) >= META_LIMIT - 1 and source == meta_n:
        repaired = repair_hard_cut(meta_n)
        return repaired, repaired
    return meta_n, source or meta_n


def author_person():
    return {
        "@type": "Person",
        "name": "Lotan Levkowitz",
        "url": f"{SITE}/",
        "jobTitle": "Co-founder and Managing Partner",
        "worksFor": {
            "@type": "Organization",
            "name": "Grove Ventures",
            "url": "https://www.grovevc.com",
        },
        "sameAs": list(SAME_AS),
        "knowsAbout": list(KNOWS_ABOUT),
    }


def enrich_person(node):
    if isinstance(node, dict):
        if node.get("@type") == "Person" and node.get("name") == "Lotan Levkowitz":
            node["sameAs"] = list(SAME_AS)
            node["knowsAbout"] = list(KNOWS_ABOUT)
        for value in node.values():
            enrich_person(value)
    elif isinstance(node, list):
        for value in node:
            enrich_person(value)


def social_tags(*, title, description, url, image, kind, published=None):
    lines = [
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(description)}">',
        f'<meta property="og:url" content="{esc(url)}">',
        f'<meta property="og:image" content="{esc(image)}">',
        f'<meta property="og:type" content="{kind}">',
        f'<meta property="og:site_name" content="{SITE_NAME}">',
    ]
    if kind == "article":
        if published:
            lines.append(f'<meta property="article:published_time" content="{esc(published)}">')
        lines.append(f'<meta property="article:author" content="{SITE}/">')
    lines += [
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:site" content="@lotanlev">',
        '<meta name="twitter:creator" content="@lotanlev">',
    ]
    return "\n".join(lines)


def upsert_social(page, tags):
    page = re.sub(
        r'\n?<meta property="og:title" content="[^"]*">.*?<meta name="twitter:creator" content="[^"]*">\n?',
        "\n",
        page,
        count=1,
        flags=re.S,
    )
    page = re.sub(
        r'(<link rel="canonical" href="[^"]*">)',
        r"\1\n" + tags,
        page,
        count=1,
    )
    return page


def published(page):
    m = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', page)
    return m.group(1) if m else ""


def html_title(page):
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    return norm_ws(htmllib.unescape(m.group(1))) if m else SITE_NAME


def h1_title(page):
    m = re.search(r'<h1 class="t">(.*?)</h1>', page, re.S)
    if not m:
        return ""
    return norm_ws(htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))))


def meta_content(page):
    m = re.search(r'<meta name="description" content="([^"]*)"', page)
    return htmllib.unescape(m.group(1)) if m else ""


def jsonld(page):
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    if not m:
        return None, None
    return json.loads(m.group(1)), m.group(0)


def replace_jsonld(page, data):
    raw = json.dumps(data, ensure_ascii=False, separators=(", ", ": "))
    script = '<script type="application/ld+json">' + raw + "</script>"
    return re.sub(
        r'<script type="application/ld\+json">.*?</script>',
        lambda _: script,
        page,
        count=1,
        flags=re.S,
    )


def set_meta_description(page, description):
    return re.sub(
        r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="{esc(description)}">',
        page,
        count=1,
    )


def load_essays():
    essays = []
    for path in sorted(glob.glob(os.path.join(ROOT, "essays", "*.html"))):
        if os.path.basename(path) == "index.html":
            continue
        slug = os.path.basename(path)[: -len(".html")]
        title = h1_title(read(path))
        essays.append(
            {
                "slug": slug,
                "title": title,
                "norm": norm_title(title),
                "url": f"/essays/{slug}.html",
            }
        )
    return essays


def matching_essay(slug, title, essays=None):
    essays = load_essays() if essays is None else essays
    for essay in essays:
        if essay["slug"] == slug:
            return essay
    n = norm_title(title)
    for essay in essays:
        if n and essay["norm"] == n:
            return essay
    return None


def expansion_line(essay):
    return (
        '<div class="prov">Expanded into an essay: '
        f'<a href="{essay["url"]}">{esc(essay["title"])}</a></div>'
    )


def apply_expansion(page, slug, title, essays):
    essay = matching_essay(slug, title, essays)
    if not essay:
        return page
    canon = f"{SITE}{essay['url']}"
    page = re.sub(
        r'<link rel="canonical" href="[^"]*">',
        f'<link rel="canonical" href="{canon}">',
        page,
        count=1,
    )
    if 'property="og:url"' in page:
        page = re.sub(
            r'<meta property="og:url" content="[^"]*">',
            f'<meta property="og:url" content="{canon}">',
            page,
            count=1,
        )
    if "Expanded into an essay:" not in page:
        line = expansion_line(essay)
        page = re.sub(
            r"(<h1 class=\"t\">.*?</h1>)",
            lambda m: m.group(1) + "\n" + line,
            page,
            count=1,
            flags=re.S,
        )
    return page


def sync_essay_expansions():
    """Point archived posts at an essay with the same slug or title."""
    essays = load_essays()
    changed = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "w", "*.html"))):
        if os.path.basename(path) == "index.html":
            continue
        slug = os.path.basename(path)[: -len(".html")]
        page = read(path)
        new = apply_expansion(page, slug, h1_title(page), essays)
        if new != page:
            write(path, new)
            changed += 1
    return changed


def card_excerpt(url):
    """Homepage card blurb for a writing URL, whitespace-collapsed."""
    index = read(os.path.join(ROOT, "index.html"))
    for chunk in re.split(r'(?=<div class="post")', index):
        if f'href="{url}"' not in chunk:
            continue
        m = re.search(r'<div class="exc">(.*?)</div>', chunk, re.S)
        if m:
            text = re.sub(r"<[^>]+>", "", m.group(1))
            return norm_ws(htmllib.unescape(text))
    return ""


def homepage_cards():
    index = read(os.path.join(ROOT, "index.html"))
    start = index.index('<div id="pl">') + len('<div id="pl">')
    end = index.index("\n</div></div>", start)
    body = index[start:end]
    idxs = [m.start() for m in re.finditer(r'<div class="post"', body)]
    cards = []
    for i, s in enumerate(idxs):
        e = idxs[i + 1] if i + 1 < len(idxs) else len(body)
        chunk = body[s:e].strip()
        href = re.search(r'href="(/(?:essays|w)/[^"]+\.html)"', chunk)
        if not href:
            continue
        dm = re.search(r'data-date="([0-9-]+)"', chunk) or re.search(
            r"</span>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", chunk
        )
        cards.append(
            {
                "url": href.group(1),
                "date": dm.group(1) if dm else "",
                "raw": chunk,
                "i": i,
            }
        )
    return cards


def render_index(kind, cards):
    if kind == "essays":
        title, desc, heading, url = (
            ESSAY_INDEX_TITLE,
            ESSAY_INDEX_DESC,
            "Essays",
            f"{SITE}/essays/",
        )
        chosen = [c for c in cards if c["url"].startswith("/essays/")]
    else:
        title, desc, heading, url = (
            NOTES_INDEX_TITLE,
            NOTES_INDEX_DESC,
            "Field notes",
            f"{SITE}/w/",
        )
        chosen = [c for c in cards if c["url"].startswith("/w/")]
    chosen.sort(key=lambda c: c["i"])
    chosen.sort(key=lambda c: c["date"], reverse=True)

    def balanced(chunk):
        # One homepage card is missing its closing div. Close it here so the
        # generated index is balanced; the homepage markup is left alone.
        extra = len(re.findall(r"<div\b", chunk)) - chunk.count("</div>")
        if extra > 0:
            chunk += "\n" + ("</div>" * extra)
        return chunk

    listing = "\n".join(balanced(c["raw"]) for c in chosen)
    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": heading,
        "url": url,
        "description": desc,
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": f"{SITE}/"},
        "author": author_person(),
    }
    social = social_tags(
        title=title,
        description=desc,
        url=url,
        image=PORTRAIT,
        kind="website",
    )
    jsonld_tag = (
        '<script type="application/ld+json">'
        + json.dumps(ld, ensure_ascii=False, separators=(", ", ": "))
        + "</script>"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
{social}
<link rel="stylesheet" href="/style.css">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{SITE}/feed.xml">
<script data-goatcounter="https://lotanvc2.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
{jsonld_tag}
</head>
<body>
<div class="wrap">
<header class="site"><div class="bar">
<h1><a href="/">Lotan Levkowitz</a></h1>
<nav><a href="/#writing">Writing</a><a href="/#about">About</a><a href="/#connect">Connect</a></nav>
</div></header>
<section id="writing">
<a class="back" href="/#writing">&larr; All writing</a>
<h2 class="section">{heading}</h2>
<div id="pl">
{listing}
</div>
</section>
<div class="cta" id="connect">
<p>Everything I write lands here first. If something resonated:</p>
<div class="row">
<a href="https://lotanl.substack.com/subscribe">Subscribe for new essays</a>
<a class="ghost" href="https://www.linkedin.com/in/lotanlevkowitz/">Follow on LinkedIn</a>
<a class="ghost" href="mailto:lotan@grovevc.com?subject=lotan.vc">Email me your take</a>
</div>
</div>
<footer>Lotan Levkowitz &middot; Grove Ventures &middot; <a href="/feed.xml" style="color:var(--faint)">RSS</a></footer>
</div>
</body>
</html>
"""


def rebuild_indexes():
    cards = homepage_cards()
    essays = render_index("essays", cards)
    notes = render_index("notes", cards)
    e_ok = write_if_changed(os.path.join(ROOT, "essays", "index.html"), essays)
    w_ok = write_if_changed(os.path.join(ROOT, "w", "index.html"), notes)
    return e_ok, w_ok


def git_lastmod(path):
    """Last commit date of a file. Uncommitted or untracked files use today."""
    if not os.path.exists(path):
        return date.today().isoformat()
    rel = os.path.relpath(path, ROOT)
    st = subprocess.run(
        ["git", "status", "--porcelain", "--", rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if st.stdout.strip():
        return date.today().isoformat()
    log = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return log.stdout.strip() or date.today().isoformat()


def file_for_loc(loc):
    if not loc.startswith(SITE):
        return None
    path = loc[len(SITE):]
    if path in ("", "/"):
        return os.path.join(ROOT, "index.html")
    if path.endswith("/"):
        return os.path.join(ROOT, path.strip("/"), "index.html")
    rel = path.lstrip("/")
    if ".." in rel.split("/"):
        return None
    return os.path.join(ROOT, rel)


def content_locs():
    """Sitemap URL order: home, essays index, essays, notes index, notes."""
    existing = []
    sm = os.path.join(ROOT, "sitemap.xml")
    if os.path.exists(sm):
        existing = re.findall(r"<loc>(.*?)</loc>", read(sm))
    locs = []

    def add(loc):
        if loc not in locs:
            locs.append(loc)

    add(f"{SITE}/")
    add(f"{SITE}/essays/")
    for loc in existing:
        if loc.startswith(f"{SITE}/essays/") and loc != f"{SITE}/essays/":
            add(loc)
    for path in sorted(glob.glob(os.path.join(ROOT, "essays", "*.html"))):
        name = os.path.basename(path)
        if name == "index.html":
            continue
        add(f"{SITE}/essays/{name}")
    add(f"{SITE}/w/")
    for loc in existing:
        if loc.startswith(f"{SITE}/w/") and loc != f"{SITE}/w/":
            add(loc)
    for path in sorted(glob.glob(os.path.join(ROOT, "w", "*.html"))):
        name = os.path.basename(path)
        if name == "index.html":
            continue
        add(f"{SITE}/w/{name}")
    return locs


def lastmod_for(loc):
    path = file_for_loc(loc)
    if loc in (f"{SITE}/", f"{SITE}/essays/", f"{SITE}/w/"):
        return git_lastmod(path)
    page = read(path)
    when = published(page)
    if not when:
        sys.exit(f"error: no datePublished for {loc}")
    return when


def rebuild_sitemap():
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc in content_locs():
        path = file_for_loc(loc)
        if not path or not os.path.exists(path):
            continue
        lines.append(f"<url><loc>{loc}</loc><lastmod>{lastmod_for(loc)}</lastmod></url>")
    lines.append("</urlset>\n")
    text = "\n".join(lines)
    return write_if_changed(os.path.join(ROOT, "sitemap.xml"), text)


def refresh_document(path, kind, essays, desc_log):
    page = read(path)
    data, _ = jsonld(page)
    if data is None:
        sys.exit(f"error: no JSON-LD in {path}")

    rel = "/" + os.path.relpath(path, ROOT).replace(os.sep, "/")
    if rel == "/index.html":
        rel = "/"
    canon = f"{SITE}/" if kind == "home" else f"{SITE}{rel}"
    if kind == "home":
        image = PORTRAIT
    else:
        hero = re.search(r'<img class="hero-img" src="(/img/[^"]+)"', page)
        if hero:
            image = SITE + hero.group(1)
        else:
            any_img = re.search(r'<img[^>]+src="(/img/[^"]+)"', page)
            image = SITE + any_img.group(1) if any_img else PORTRAIT

    description = meta_content(page)
    if kind == "post":
        ld_desc = data.get("description", "") if isinstance(data, dict) else ""
        card = card_excerpt(rel)
        new_meta, full = descriptions_for(description, [ld_desc, card])
        if new_meta != norm_ws(description):
            desc_log.append((rel, norm_ws(description), new_meta))
        page = set_meta_description(page, new_meta)
        description = new_meta
        if isinstance(data, dict) and norm_ws(data.get("description", "")) != norm_ws(full):
            data["description"] = full
    elif kind == "essay":
        description = norm_ws(description)

    enrich_person(data)
    page = replace_jsonld(page, data)

    og_type = "website" if kind == "home" else "article"
    when = published(page) if og_type == "article" else ""
    if kind == "post":
        essay = matching_essay(os.path.basename(path)[: -len(".html")], h1_title(page), essays)
        if essay:
            canon = f"{SITE}{essay['url']}"
    tags = social_tags(
        title=html_title(page),
        description=description,
        url=canon,
        image=image,
        kind=og_type,
        published=when or None,
    )
    # Canonical may move to the essay. Set it before inserting og:url.
    if kind == "post":
        page = re.sub(
            r'<link rel="canonical" href="[^"]*">',
            f'<link rel="canonical" href="{canon}">',
            page,
            count=1,
        )
    page = upsert_social(page, tags)
    if kind == "post":
        page = apply_expansion(
            page,
            os.path.basename(path)[: -len(".html")],
            h1_title(page),
            essays,
        )
    write_if_changed(path, page)


def refresh_all():
    essays = load_essays()
    desc_log = []
    refresh_document(os.path.join(ROOT, "index.html"), "home", essays, desc_log)
    for path in sorted(glob.glob(os.path.join(ROOT, "essays", "*.html"))):
        if os.path.basename(path) == "index.html":
            continue
        refresh_document(path, "essay", essays, desc_log)
    for path in sorted(glob.glob(os.path.join(ROOT, "w", "*.html"))):
        if os.path.basename(path) == "index.html":
            continue
        refresh_document(path, "post", essays, desc_log)
    rebuild_indexes()
    rebuild_sitemap()
    return desc_log


def check():
    """Exit 1 when a published page, sitemap entry, or social image is wrong."""
    errors = []

    def err(msg):
        errors.append(msg)

    pages = [os.path.join(ROOT, "index.html")]
    pages += sorted(glob.glob(os.path.join(ROOT, "essays", "*.html")))
    pages += sorted(glob.glob(os.path.join(ROOT, "w", "*.html")))
    for path in pages:
        rel = os.path.relpath(path, ROOT)
        page = read(path)
        if "<html" not in page.lower() or "</html>" not in page.lower():
            err(f"{rel}: does not look like an HTML document")
        data, _ = jsonld(page)
        if data is None:
            err(f"{rel}: JSON-LD missing or not JSON")
        else:
            people = []

            def walk(node):
                if isinstance(node, dict):
                    if node.get("@type") == "Person" and node.get("name") == "Lotan Levkowitz":
                        people.append(node)
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)

            walk(data)
            if not people:
                err(f"{rel}: no Lotan Levkowitz Person")
            for person in people:
                if person.get("sameAs") != SAME_AS:
                    err(f"{rel}: sameAs mismatch {person.get('sameAs')}")
                if person.get("knowsAbout") != KNOWS_ABOUT:
                    err(f"{rel}: knowsAbout mismatch")
                works = person.get("worksFor")
                if isinstance(works, dict) and works.get("url") not in (None, "https://www.grovevc.com"):
                    err(f"{rel}: worksFor url changed")
        for prop in (
            "og:title",
            "og:description",
            "og:url",
            "og:image",
            "og:type",
            "og:site_name",
        ):
            if f'property="{prop}"' not in page:
                err(f"{rel}: missing {prop}")
        if 'name="twitter:card" content="summary_large_image"' not in page:
            err(f"{rel}: twitter card")
        if 'name="twitter:site" content="@lotanlev"' not in page:
            err(f"{rel}: twitter:site")
        if 'name="twitter:creator" content="@lotanlev"' not in page:
            err(f"{rel}: twitter:creator")
        og_type = re.search(r'property="og:type" content="([^"]*)"', page)
        if rel in ("index.html", "essays/index.html", "w/index.html"):
            if not og_type or og_type.group(1) != "website":
                err(f"{rel}: og:type should be website")
        else:
            if not og_type or og_type.group(1) != "article":
                err(f"{rel}: og:type should be article")
            if "article:published_time" not in page or "article:author" not in page:
                err(f"{rel}: missing article meta")
        img = re.search(r'property="og:image" content="([^"]*)"', page)
        if not img:
            err(f"{rel}: no og:image")
        else:
            url = htmllib.unescape(img.group(1))
            if not url.startswith(f"{SITE}/img/"):
                err(f"{rel}: og:image is not an absolute site image ({url})")
            else:
                local = os.path.join(ROOT, url[len(SITE) + 1:])
                if not os.path.isfile(local):
                    err(f"{rel}: og:image file missing {url}")
        canon = re.search(r'<link rel="canonical" href="([^"]*)"', page)
        og_url = re.search(r'property="og:url" content="([^"]*)"', page)
        if not canon or not og_url or canon.group(1) != og_url.group(1):
            err(f"{rel}: og:url does not match canonical")
        if rel.startswith("w/") and rel != "w/index.html":
            desc = meta_content(page)
            if len(desc) > META_LIMIT:
                err(f"{rel}: meta description is {len(desc)} chars")
            if len(desc) >= META_LIMIT - 1 and not desc.endswith((ELLIPSIS, ".", "!", "?")):
                err(f"{rel}: meta description looks cut mid-word: {desc[-24:]!r}")

    essays = load_essays()
    for path in sorted(glob.glob(os.path.join(ROOT, "w", "*.html"))):
        if os.path.basename(path) == "index.html":
            continue
        slug = os.path.basename(path)[: -len(".html")]
        page = read(path)
        essay = matching_essay(slug, h1_title(page), essays)
        rel = os.path.relpath(path, ROOT)
        if not essay:
            if "Expanded into an essay:" in page:
                err(f"{rel}: expansion line without a matching essay")
            continue
        canon = re.search(r'<link rel="canonical" href="([^"]*)"', page)
        expect = f"{SITE}{essay['url']}"
        if not canon or canon.group(1) != expect:
            err(f"{rel}: canonical should be {expect}")
        if f'href="{essay["url"]}"' not in page or "Expanded into an essay:" not in page:
            err(f"{rel}: missing expansion line")
        essay_page = read(os.path.join(ROOT, essay["url"].lstrip("/")))
        own = re.search(r'<link rel="canonical" href="([^"]*)"', essay_page)
        if not own or own.group(1) != f"{SITE}{essay['url']}":
            err(f"essay canonical changed for {essay['url']}")

    sm = read(os.path.join(ROOT, "sitemap.xml"))
    locs = re.findall(r"<loc>(.*?)</loc>", sm)
    lastmods = re.findall(r"<lastmod>(.*?)</lastmod>", sm)
    if len(locs) != len(lastmods):
        err("sitemap: a URL is missing lastmod")
    for loc, lm in zip(locs, lastmods):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", lm):
            err(f"sitemap: bad lastmod for {loc}")
        path = file_for_loc(loc)
        if not path or not os.path.isfile(path):
            err(f"sitemap: {loc} does not map to a file")
        elif loc not in (f"{SITE}/", f"{SITE}/essays/", f"{SITE}/w/"):
            if published(read(path)) != lm:
                err(f"sitemap: lastmod {lm} != datePublished for {loc}")
    expected = set(content_locs())
    if set(locs) != expected:
        err(f"sitemap: missing {sorted(expected - set(locs))[:8]} extra {sorted(set(locs) - expected)[:8]}")
    robots = read(os.path.join(ROOT, "robots.txt"))
    if f"Sitemap: {SITE}/sitemap.xml" not in robots:
        err("robots.txt lost its sitemap reference")

    # Indexes are newest-first and list every piece.
    for folder, prefix in (("essays", "/essays/"), ("w", "/w/")):
        idx = read(os.path.join(ROOT, folder, "index.html"))
        hrefs = re.findall(r'<h4><a href="([^"]+)"', idx)
        if any(not h.startswith(prefix) for h in hrefs):
            err(f"{folder}/index.html lists an unexpected URL")
        on_disk = {
            f"/{folder}/{os.path.basename(p)}"
            for p in glob.glob(os.path.join(ROOT, folder, "*.html"))
            if os.path.basename(p) != "index.html"
        }
        if set(hrefs) != on_disk:
            err(f"{folder}/index.html does not list every page")
        dates = []
        for chunk in re.split(r'(?=<div class="post")', idx)[1:]:
            dm = re.search(r'data-date="([0-9-]+)"', chunk) or re.search(
                r"</span>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", chunk
            )
            dates.append(dm.group(1) if dm else "")
        if dates != sorted(dates, reverse=True):
            err(f"{folder}/index.html is not newest first")

    if errors:
        print(f"{len(errors)} check(s) failed:")
        for e in errors:
            print(" -", e)
        return 1
    print(f"ok — {len(pages)} HTML pages, {len(locs)} sitemap URLs")
    return 0


def main():
    if "--check" in sys.argv:
        sys.exit(check())
    log = refresh_all()
    print(f"refreshed pages; {len(log)} meta description(s) rewrapped")
    for rel, old, new in log:
        print(f"  {rel}")
        print(f"    - {old}")
        print(f"    + {new}")


if __name__ == "__main__":
    main()
