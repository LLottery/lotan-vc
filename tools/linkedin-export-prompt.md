# LinkedIn export prompt

Paste the block below into Claude Desktop (the client with browser access, signed
in to LinkedIn as Lotan). It exports recent posts into files that
`tools/ingest.py` consumes directly.

Change the date on the first line to control the window. The site's newest post
is the safe starting point — overlap is harmless, because `ingest.py` refuses a
slug that already exists.

---

Export my LinkedIn posts published on or after 2026-07-01.

I am signed in to LinkedIn in this browser. These are my own posts on my own
account. Work in a folder called `linkedin-export` in my home directory; create
it if it does not exist.

**1. Collect the posts**

Open https://www.linkedin.com/in/lotanlevkowitz/recent-activity/all/ and scroll
until you reach posts older than the cutoff date. Click every "…see more" so no
text stays truncated.

Include only original posts I authored. Skip reposts, shares of other people's
posts, comments, and reactions.

**2. Get each post's exact date from its ID**

Every post URL contains `urn:li:activity:<id>`. The ID encodes its publish time:

    timestamp_ms = activity_id >> 22
    date = UTC date of that timestamp, formatted YYYY-MM-DD

Use this, not the "2w ago" label. It is exact. Verified against 10 published
posts, all matching.

**3. For each post, write `linkedin-export/<slug>.json`**

`<slug>` is the title lowercased, non-alphanumerics replaced with hyphens.

    {
      "title":        "Short declarative title you propose",
      "date":         "2026-07-22",
      "theme":        "one theme from the list below",
      "linkedin_url": "https://www.linkedin.com/feed/update/urn:li:activity:<id>/",
      "excerpt":      "One or two sentences for the site card and RSS.",
      "body_en":      "Paragraph.\n\nParagraph.",
      "body_he":      "",
      "image":        "linkedin-export/<id>.jpg",
      "language":     "en",
      "english_is_machine_translation": false
    }

Themes — pick the closest, or propose a new one and say so:

    AI Market Structure · Service as Software · Founder-Investor Dynamics
    Founder Validation · Data Moats · Where to Build · Why We Invested
    AI and Work · Investing Posture · Founder Patterns · SaaS under AI
    Company Formation · GTM Data Layer · Building AI Products
    Enterprise AI · Frameworks

**4. Language rules — important**

Copy the post text verbatim. Do not rewrite, tighten, or improve it.

- Post in English → put it in `body_en`, leave `body_he` empty, `"language": "en"`.
- Post in Hebrew → put the Hebrew verbatim in `body_he`, set `"language": "he"`,
  put your English translation in `body_en`, and set
  `"english_is_machine_translation": true`.

That flag matters. The site credits English versions to the author, so a
translated post must not be published under that line until Lotan writes or
approves the English himself. Never set the flag to false for text you produced.

**5. Images**

Download each post's main image to `linkedin-export/<activity_id>.jpg`. Skip
video thumbnails and link-preview images — only images I attached. If a post has
no image, omit the `image` field entirely.

**6. Report back**

Print a table of what you exported: date, title, theme, language, whether an
image was saved. Then list anything you skipped and why, and flag any post where
the title or theme was a genuine guess.

Do not post, like, comment, follow, connect, or message anyone. Read and
download only.
