Enrich my LinkedIn export. No browser needed — everything is in the zip.

INPUT

Unzip linkedin-export.zip. You get a flat folder:

    <slug>.json     one per post
    <id>.jpg        images
    _index.json     manifest listing every post and what needs work

Read _index.json first. Every post with "needs_editorial": true needs three
fields written and, if Hebrew, a decision about body_en.

DO NOT TOUCH

body_he and body_en are verbatim post text. Never rewrite, tighten, translate
in place, fix typos, or "improve" them. If you change a single character of a
body field you have broken the export.

Do not touch: date, linkedin_url, image, figures, language, body_sha256,
text_witness.

body_sha256 is the hex SHA-256 of the UTF-8 bytes of the body string
(body_he for Hebrew posts, body_en otherwise). text_witness is a readable
companion: "<charCount> chars | <first 40> ... <last 40>".

Ingest recomputes body_sha256 and rejects the whole bundle if it does not
match. Do not recompute, refresh, or "fix" either field — if a hash mismatches,
the body was altered and that is the bug to report, not the hash. Never edit a
body to make a hash match.

You may verify your own work before re-zipping:

    python3 - <<'EOF'
    import hashlib, json, glob, sys
    bad = 0
    for f in glob.glob('linkedin-export/*.json'):
        if f.endswith('_index.json'): continue
        d = json.load(open(f, encoding='utf-8'))
        body = d['body_he'] if d['language'] == 'he' else d['body_en']
        got = hashlib.sha256(body.encode('utf-8')).hexdigest()
        if got != d.get('body_sha256'):
            print('MISMATCH', f); bad += 1
    print('bodies intact' if not bad else f'{bad} ALTERED')
    EOF

WRITE THREE FIELDS PER POST

title    Short declarative. No colons, no em dashes, no hype words. It becomes
         the filename slug, so keep it plain. Prefer the post's own argument
         over its opening line. The auto-generated title in the file is a
         placeholder — replace it, don't polish it.

theme    Exactly one from this list. If nothing fits, propose a new one and
         say so in your report rather than forcing a bad match:

           AI Market Structure · Service as Software · Founder-Investor Dynamics
           Founder Validation · Data Moats · Where to Build · Why We Invested
           AI and Work · Investing Posture · Founder Patterns · SaaS under AI
           Company Formation · GTM Data Layer · Building AI Products
           Enterprise AI · Frameworks

excerpt  One or two sentences for the site card and RSS. Written in my voice:
         sharp, specific, no throat-clearing. It should state the claim, not
         advertise that a claim is coming. Not a summary of the post — the
         hook that makes someone read it.

Then set "needs_editorial": false.

HEBREW POSTS

body_en is empty by design. english_is_machine_translation is already true.

Do not fill body_en unless I explicitly ask. The site credits English versions
to me, and a machine translation must not publish under that line until I
write or approve it myself. Leaving it empty is correct, not incomplete.

If I do ask for translations: put them in body_en, keep the flag true, and
never set it false for text you produced.

Titles, themes and excerpts for Hebrew posts should be written in ENGLISH —
those are site metadata, not the post.

SLUG RENAME

The filename is the title lowercased with non-alphanumerics replaced by
hyphens. When you change a title, rename the file to match, and note the
rename. Do not rename images.

FLAG, DON'T GUESS QUIETLY

Report at the end:

  - a table: date, title, theme, language, images
  - every post where the theme was a genuine guess, and what the runner-up was
  - any post you'd argue does not belong on the site at all (event
    announcements, pure congratulations, job postings) — do not delete them,
    just flag them
  - anything in _index.json's "warnings" you could not resolve, especially
    document/carousel posts whose slides were never exported
  - any gap in "suspicious_gaps" that looks like a real collection failure

VOICE

Opinionated over neutral. Concrete over abstract. No motivational tone, no
emojis, no long dashes, no "in today's fast-moving landscape". If an excerpt
could sit on any VC's blog, it is wrong.
