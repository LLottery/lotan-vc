#!/usr/bin/env python3
"""
Ingest a LinkedIn post into lotan.vc.

Takes one JSON file describing a post and performs every mechanical step:
  1. writes w/<slug>.html using the site template
  2. inserts the card into the writing list in index.html (reverse-chronological)
  3. updates the theme filter counts
  4. adds an item to feed.xml
  5. adds a URL to sitemap.xml
  6. copies the hero image into img/

Usage:
    python3 tools/ingest.py post.json            # apply
    python3 tools/ingest.py post.json --dry-run  # show what would change

See tools/README.md for the input format.
"""

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSP = (
    "default-src 'self'; script-src 'self' https://gc.zgo.at 'unsafe-inline'; "
    "connect-src https://lotanvc2.goatcounter.com; img-src 'self' "
    "https://lotanvc2.goatcounter.com; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self' mailto:"
)

ESSAYS = [
    ("/essays/show-me-the-flywheel.html", "Show Me the Flywheel", "Data Moats"),
    ("/essays/service-as-software.html", "Services Are the Next Software", "Service as Software"),
    ("/essays/the-enterprise-ai-startup-playbook.html", "The Enterprise-AI Startup Playbook", "Enterprise AI"),
    ("/essays/the-ai-conversation-were-not-having.html", "The AI Conversation We're Not Having", "AI Market Structure"),
]


def esc(s):
    """Escape text the way the existing pages do."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def slugify(title):
    s = unicodedata.normalize("NFKD", title)
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)


def activity_id(url):
    m = re.search(r"(?:activity[:\-])(\d+)", url or "")
    return m.group(1) if m else None


def resolve(base, path):
    """Resolve an asset path against the JSON file's own directory.

    Falls back to the path as given, so both a bundle of files sitting next to
    the JSON and an absolute path from elsewhere work.
    """
    if os.path.isabs(path):
        return path
    near = os.path.join(base, path)
    return near if os.path.exists(near) else path


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


# --------------------------------------------------------------------------
# parsing the existing writing list
# --------------------------------------------------------------------------

CARD_MARK = '<div class="post" data-th="'


def parse_index(html):
    """Return (prefix, [cards], suffix) for the #pl writing list."""
    start = html.index('<div id="pl">') + len('<div id="pl">')
    end = html.index("\n</div></div>", start)
    body = html[start:end]

    idxs = [m.start() for m in re.finditer(re.escape(CARD_MARK), body)]
    cards = []
    for i, s in enumerate(idxs):
        e = idxs[i + 1] if i + 1 < len(idxs) else len(body)
        chunk = body[s:e]
        theme = re.search(r'data-th="([^"]*)"', chunk).group(1)
        dm = re.search(r"</span>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", chunk)
        sm = re.search(r'href="(/w/[^"]+\.html)"', chunk)
        tm = re.search(r"<h4><a [^>]*>(.*?)</a></h4>", chunk, re.S)
        cards.append(
            {
                "raw": chunk,
                "theme": theme,
                "date": dm.group(1) if dm else "",
                "url": sm.group(1) if sm else "",
                "title": tm.group(1) if tm else "",
            }
        )
    return html[:start], cards, html[end:]


def build_card(p):
    img = (
        f'<a href="{p["url"]}"><img src="/img/{p["image_name"]}" alt="" loading="lazy"></a>'
        if p.get("image_name")
        else ""
    )
    return (
        f'{CARD_MARK}{esc(p["theme"])}">\n'
        f'<div class="txt">\n'
        f'<div class="meta"><span class="tag">{esc(p["theme"])}</span> {p["date"]}</div>\n'
        f'<h4><a href="{p["url"]}">{esc(p["title"])}</a></h4>\n'
        f'<div class="exc">{esc(p["excerpt"])}</div>\n'
        f'<div style="margin-top:8px"><a class="more" href="{p["url"]}">Read &rarr;</a></div>\n'
        f"</div>{img}\n"
        f"</div>"
    )


# --------------------------------------------------------------------------
# page builder
# --------------------------------------------------------------------------


def build_related(cards, theme, self_url):
    """Up to 3 same-theme posts, then a topical essay."""
    same = [c for c in cards if c["theme"] == theme and c["url"] != self_url]
    same.sort(key=lambda c: c["date"], reverse=True)
    out = []
    for c in same[:3]:
        out.append(
            f'<div class="r"><a href="{c["url"]}">{c["title"]}</a>'
            f'<div class="meta">{esc(c["theme"])} &middot; {c["date"]}</div></div>'
        )
    essay = next((e for e in ESSAYS if e[2] == theme), ESSAYS[0])
    out.append(
        f'<div class="r"><a href="{essay[0]}">{esc(essay[1])} (essay)</a>'
        f'<div class="meta">{esc(essay[2])}</div></div>'
    )
    return '<aside class="rel"><h3>Keep reading</h3>' + "".join(out) + "</aside>"


def build_page(p, related):
    def figure_html(f):
        cap = f'<figcaption>{esc(f["caption"])}</figcaption>' if f["caption"] else ""
        return (
            f'<figure><img src="/img/{f["name"]}" alt="{esc(f["caption"])}" '
            f'loading="lazy">{cap}</figure>'
        )

    # A figure with after_paragraph lands under that paragraph; the rest follow
    # the body in the order given.
    after, trailing = {}, []
    for f in p.get("figures") or []:
        n = f.get("after")
        if isinstance(n, int) and 1 <= n <= len(p["body_en"]):
            after.setdefault(n, []).append(f)
        else:
            trailing.append(f)

    chunks = []
    for i, x in enumerate(p["body_en"], start=1):
        chunks.append(f"<p>{esc(x)}</p>")
        chunks.extend(figure_html(f) for f in after.get(i, []))
    chunks.extend(figure_html(f) for f in trailing)
    paras = "".join(chunks)

    hero = f'\n<img class="hero-img" src="/img/{p["image_name"]}" alt="">' if p.get("image_name") else ""

    hebrew = ""
    if p.get("body_he"):
        hebrew = (
            '\n<details class="he"><summary>Read the Hebrew original</summary>'
            f'<div>{esc(p["body_he"])}</div></details>'
        )

    prov_tail = " Originally written in Hebrew; English version by the author." if p.get("body_he") else ""
    if p.get("linkedin_url"):
        prov = (
            f'\n<div class="prov">First published <a href="{p["linkedin_url"]}" '
            f'rel="noopener">on LinkedIn</a>, {p["date"]}.{prov_tail}</div>'
        )
    else:
        prov = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(p["title"])} &mdash; Lotan Levkowitz</title>
<meta name="description" content="{esc(p["excerpt"][:155])}">
<link rel="canonical" href="https://lotan.vc{p["url"]}">
<link rel="stylesheet" href="/style.css">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<link rel="alternate" type="application/rss+xml" title="Lotan Levkowitz" href="https://lotan.vc/feed.xml">
<script data-goatcounter="https://lotanvc2.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
</head>
<body>
<div class="wrap">
<header class="site"><div class="bar">
<h1><a href="/">Lotan Levkowitz</a></h1>
<nav><a href="/#writing">Writing</a><a href="/#about">About</a><a href="/#connect">Connect</a></nav>
</div></header>
<div class="pgrid">
<article class="piece">
<a class="back" href="/#writing">&larr; All writing</a>
<div class="meta"><span class="tag">{esc(p["theme"])}</span> {p["date"]}</div>
<h1 class="t">{esc(p["title"])}</h1>{hero}
<div class="body">{paras}</div>{hebrew}{prov}
</article>
{related}
</div>
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
<script>
(function(){{if(!document.querySelector('article.piece'))return;
var slug=location.pathname.replace(/\\.html$/,'').split('/').pop();
var t=0,fired={{}},maxs=0;
function ev(p){{if(fired[p])return;fired[p]=1;if(window.goatcounter&&window.goatcounter.count)window.goatcounter.count({{path:p,event:true}});}}
setInterval(function(){{if(!document.hidden){{t+=5;
if(t>=30)ev('read-30s-'+slug);
if(t>=120)ev('read-2m-'+slug);}}}},5000);
window.addEventListener('scroll',function(){{var d=document.documentElement;
var p=(window.scrollY+window.innerHeight)/d.scrollHeight;
if(p>maxs)maxs=p;if(maxs>0.85)ev('read-done-'+slug);}},{{passive:true}});
}})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# filters / feed / sitemap
# --------------------------------------------------------------------------


def update_filters(html, theme):
    """Increment the 'All' count and the count for `theme` by one.

    Deliberately incremental rather than recomputed: the hand-maintained counts
    exclude at least one externally-linked card, and a full rebuild would
    silently rewrite numbers this change has no opinion about.
    """
    aside = re.search(r'<aside class="filters">.*?</aside>', html, re.S)
    if not aside:
        return html
    block = aside.group(0)

    def bump(m):
        return f"{m.group(1)}({int(m.group(2)) + 1})"

    new = re.sub(r"(>All )\((\d+)\)", bump, block, count=1)

    pat = r"(>" + re.escape(esc(theme)) + r" )\((\d+)\)"
    if re.search(pat, new):
        new = re.sub(pat, bump, new, count=1)
    else:  # first post in a brand-new theme
        link = f"<a onclick=\"ft('{esc(theme)}',this)\">{esc(theme)} (1)</a>"
        new = new.replace("</aside>", link + "</aside>")

    return html.replace(block, new, 1)


def update_feed(xml, p):
    item = (
        f'<item><title>{esc(p["title"])}</title>'
        f'<link>https://lotan.vc{p["url"]}</link>'
        f'<guid>https://lotan.vc{p["url"]}</guid>'
        f'<description>{esc(p["excerpt"])}</description></item>\n'
    )
    if f"https://lotan.vc{p['url']}</link>" in xml:
        return xml, False
    i = xml.index("<item>")
    return xml[:i] + item + xml[i:], True


def update_sitemap(xml, p):
    url = f"<url><loc>https://lotan.vc{p['url']}</loc></url>"
    if url in xml:
        return xml, False
    i = xml.index("<url><loc>https://lotan.vc/w/")
    return xml[:i] + url + "\n" + xml[i:], True


# --------------------------------------------------------------------------


def load_post(path):
    p = json.load(open(path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(path))

    for k in ("title", "date", "theme", "body_en"):
        if not p.get(k):
            sys.exit(f"error: missing required field '{k}' in {path}")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["date"]):
        sys.exit(f"error: date must be YYYY-MM-DD, got {p['date']!r}")

    if isinstance(p["body_en"], str):
        p["body_en"] = [x.strip() for x in re.split(r"\n\s*\n", p["body_en"].strip()) if x.strip()]

    p["slug"] = p.get("slug") or slugify(p["title"])
    p["url"] = f"/w/{p['slug']}.html"

    if not p.get("excerpt"):
        p["excerpt"] = p["body_en"][0][:300]

    aid = activity_id(p.get("linkedin_url", ""))
    stem = aid or p["slug"]

    p["image_name"] = None
    src = p.get("image")
    if src:
        src = resolve(base, src)
        if not os.path.exists(src):
            sys.exit(f"error: image not found: {p['image']}")
        ext = os.path.splitext(src)[1] or ".jpg"
        p["image_name"] = f"{stem}{ext}"
        p["image_src"] = src

    # Additional visuals. Accepts plain paths or
    # {file, caption, after_paragraph}; numbering continues from the hero.
    figures = []
    for i, f in enumerate(p.get("figures") or [], start=2):
        if isinstance(f, str):
            f = {"file": f}
        raw = f.get("file")
        if not raw:
            continue
        path = resolve(base, raw)
        if not os.path.exists(path):
            sys.exit(f"error: figure not found: {raw}")
        ext = os.path.splitext(path)[1] or ".jpg"
        figures.append(
            {
                "src": path,
                "name": f"{stem}-{i}{ext}",
                "caption": (f.get("caption") or "").strip(),
                "after": f.get("after_paragraph"),
            }
        )
    p["figures"] = figures
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    p = load_post(a.post)
    page_path = os.path.join(ROOT, "w", f"{p['slug']}.html")

    index = read(os.path.join(ROOT, "index.html"))
    prefix, cards, suffix = parse_index(index)

    if any(c["url"] == p["url"] for c in cards) or os.path.exists(page_path):
        sys.exit(f"error: {p['url']} already exists — pick a different slug or remove it first")

    related = build_related(cards, p["theme"], p["url"])
    page = build_page(p, related)

    # insert reverse-chronologically
    card = {**p, "raw": build_card(p)}
    pos = next((i for i, c in enumerate(cards) if c["date"] and c["date"] < p["date"]), len(cards))
    new_cards = cards[:pos] + [card] + cards[pos:]

    new_index = prefix + "".join(c["raw"] for c in new_cards) + suffix
    new_index = update_filters(new_index, p["theme"])

    feed, feed_ok = update_feed(read(os.path.join(ROOT, "feed.xml")), p)
    sm, sm_ok = update_sitemap(read(os.path.join(ROOT, "sitemap.xml")), p)

    print(f"  page      w/{p['slug']}.html ({len(p['body_en'])} paragraphs"
          f"{', + Hebrew' if p.get('body_he') else ''})")
    print(f"  index     card #{pos + 1} of {len(new_cards)}  [{p['theme']}] {p['date']}")
    print(f"  filters   All ({len(new_cards)})")
    print(f"  feed.xml  {'added' if feed_ok else 'already present'}")
    print(f"  sitemap   {'added' if sm_ok else 'already present'}")
    figs = p.get("figures") or []
    print(f"  image     {p['image_name'] or 'none'}")
    if figs:
        for f in figs:
            where = f"after para {f['after']}" if isinstance(f.get("after"), int) else "end of body"
            print(f"  figure    {f['name']}  ({where})")

    if a.dry_run:
        print("\ndry run — nothing written")
        return

    if p.get("image_name"):
        shutil.copyfile(p["image_src"], os.path.join(ROOT, "img", p["image_name"]))
    for f in p.get("figures") or []:
        shutil.copyfile(f["src"], os.path.join(ROOT, "img", f["name"]))

    write(page_path, page)
    write(os.path.join(ROOT, "index.html"), new_index)
    write(os.path.join(ROOT, "feed.xml"), feed)
    write(os.path.join(ROOT, "sitemap.xml"), sm)
    print(f"\ndone → https://lotan.vc{p['url']}")


if __name__ == "__main__":
    main()
