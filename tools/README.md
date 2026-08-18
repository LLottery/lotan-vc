# Ingest

`ingest.py` turns one LinkedIn post into a fully wired page on lotan.vc.

```bash
python3 tools/ingest.py post.json --dry-run   # preview
python3 tools/ingest.py post.json             # apply

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
7. Copies any additional visuals into `img/` as `<id>-2.jpg`, `<id>-3.jpg`, and
   renders them as figures in the body. `after_paragraph` places one under a
   given paragraph; the rest follow the text. Captions are optional and become
   both the `<figcaption>` and the image's alt text.

Counts are incremented rather than recomputed on purpose: the hand-maintained
numbers exclude an externally-linked card, and a rebuild would rewrite figures
this script has no opinion about.

The script refuses to overwrite an existing slug, and re-running it will not
duplicate feed or sitemap entries.

## Getting the post text

LinkedIn answers unauthenticated requests with HTTP 999, so the text cannot be
fetched from here. `linkedin-export-prompt.md` is a prompt to paste into Claude
Desktop, which has a signed-in browser: it exports recent posts as JSON files in
exactly the shape `ingest.py` expects, plus their images.

Post dates come from the activity id rather than LinkedIn's relative labels:

    timestamp_ms = activity_id >> 22

Verified against 10 published posts, all exact.

## Ingesting a whole export

`ingest-zip.py` takes the zip the export prompt produces and runs every post in
it through `ingest.py`, oldest first so the writing list ends up ordered:

```bash
python3 tools/ingest-zip.py linkedin-export.zip --dry-run
python3 tools/ingest-zip.py linkedin-export.zip
git add -A && git commit -m "Add posts" && git push
```

Asset paths in each JSON resolve against the JSON's own directory, so a flat
bundle of posts and images works with bare filenames.

Posts marked `"english_is_machine_translation": true` are held back rather than
published, because the page template credits English versions to the author.
Approve or rewrite the English, set the flag to false, and re-run.
