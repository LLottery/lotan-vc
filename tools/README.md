# Ingest

`ingest.py` turns one LinkedIn post into a fully wired page on lotan.vc.

```bash
python3 tools/ingest.py post.json --dry-run   # preview
python3 tools/ingest.py post.json             # apply
git add -A && git commit -m "Add post: <title>" && git push
```

GitHub Pages redeploys about a minute after the push.

## Why there is no automatic fetch

LinkedIn answers unauthenticated requests with HTTP 999 and publishes no feed
for a profile's posts, so the post text cannot be pulled programmatically. The
Substack feed is empty and mirrors nothing. Supplying the text is therefore the
one manual step; everything downstream of it is handled here.

## Input

```json
{
  "title":        "Service as Software: three company types",
  "date":         "2026-07-06",
  "theme":        "Service as Software",
  "linkedin_url": "https://www.linkedin.com/feed/update/urn:li:activity:7479776207828475904/",
  "excerpt":      "One or two sentences for the card and the RSS item.",
  "body_en":      "Paragraph one.\n\nParagraph two.",
  "body_he":      "פסקה ראשונה.\n\nפסקה שנייה.",
  "image":        "/path/to/hero.jpg"
}
```

Required: `title`, `date` (YYYY-MM-DD), `theme`, `body_en`.

Optional: `linkedin_url` (adds the provenance line and names the image after the
activity id), `excerpt` (defaults to the first paragraph), `body_he` (adds the
collapsible Hebrew original and the "originally written in Hebrew" note),
`image`, `slug` (defaults to a slugified title).

`body_en` may be a single string with blank lines between paragraphs, or a list
of paragraph strings.

## What it does

1. Writes `w/<slug>.html` from the site template — head, CSP, canonical,
   GoatCounter, hero image, Hebrew `<details>`, provenance, read-depth script.
2. Builds the "Keep reading" sidebar: up to three most recent same-theme posts
   plus a topical essay.
3. Inserts the card into `#pl` in `index.html` in reverse-chronological order,
   leaving the interleaved ESSAY cards where they are.
4. Increments the "All" and per-theme counts in the filter sidebar, adding a new
   theme link if the theme is new.
5. Prepends an item to `feed.xml` and a URL to `sitemap.xml`.
6. Copies the hero image into `img/`, named after the LinkedIn activity id to
   match the existing convention.

Counts are incremented rather than recomputed on purpose: the hand-maintained
numbers exclude an externally-linked card, and a rebuild would rewrite figures
this script has no opinion about.

The script refuses to overwrite an existing slug, and re-running it will not
duplicate feed or sitemap entries.
