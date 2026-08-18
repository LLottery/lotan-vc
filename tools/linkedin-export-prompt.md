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
      "image":        "<id>.jpg",
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

**5. Visuals — capture every one**

Many posts carry more than one visual. Save them all into `linkedin-export/`,
named `<activity_id>.jpg`, `<activity_id>-2.jpg`, `<activity_id>-3.jpg`, and so
on, in the order they appear in the post. Download at the largest resolution
LinkedIn serves, not the feed thumbnail.

Cover each of these:

- Single images and multi-image posts — every image, not just the first.
- Diagrams, charts, and frameworks. These matter most; they are usually the
  point of the post.
- Document/carousel posts (PDF decks). Export every slide as its own image,
  in order.
- Videos — save the poster frame and note in your report that the post has a
  video the site will not carry.

Skip link-preview thumbnails, profile photos, company logos, and reaction icons.

Then record them in the JSON. The first visual is the hero; the rest become
figures:

    "image": "<id>.jpg",
    "figures": [
      {"file": "<id>-2.jpg",
       "caption": "Short caption, or omit if the image speaks for itself",
       "after_paragraph": 3},
      "<id>-3.jpg"
    ]

`after_paragraph` places a figure directly under that paragraph, counting from
1. Use it when the post text clearly refers to the visual at a particular point
— a diagram introduced mid-argument, a slide that illustrates one step. If the
placement is not obvious, leave it out and the figure goes after the body. A
bare path string is fine when there is no caption and no placement.

If a post has no visuals, omit both fields.

**6. Zip the folder**

Put every JSON file and every image directly in `linkedin-export/`, flat, with
no subfolders. Asset paths in the JSON are bare filenames because the files sit
beside it.

Then zip the whole folder to `linkedin-export.zip` in my home directory, and
tell me where it is so I can upload it.

**7. Report back**

Print a table of what you exported: date, title, theme, language, whether an
image was saved. Then list anything you skipped and why, and flag any post where
the title or theme was a genuine guess.

Do not post, like, comment, follow, connect, or message anyone. Read and
download only.
