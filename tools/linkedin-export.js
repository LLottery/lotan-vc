
/* =========================================================================
   LinkedIn post exporter  —  paste into DevTools console
   =========================================================================

   HOW TO USE
   1. Open  https://www.linkedin.com/in/lotanlevkowitz/recent-activity/all/
   2. Open DevTools (Cmd+Option+J on Mac) -> Console tab
   3. If Chrome asks you to type "allow pasting", type it and press Enter
   4. Paste this entire file, press Enter
   5. A panel appears top-left. SCROLL THE PAGE DOWN YOURSELF with your
      trackpad/mouse. The panel counts posts and shows the oldest date found.
      Keep scrolling until it turns green and says CUTOFF REACHED.
   6. Click "BUILD + DOWNLOAD ZIP". One file lands in ~/Downloads.

   WHY YOU SCROLL INSTEAD OF THE SCRIPT
   LinkedIn's lazy-loader only fires on real user scroll events. Scripted
   scrolling silently fails to load more posts. Your hand on the trackpad is
   the reliable trigger. The script harvests continuously while you scroll,
   into a persistent store, so LinkedIn evicting posts from the DOM (which it
   does aggressively) cannot lose anything you have already passed.

   WHAT IT PRODUCES
   linkedin-export.zip containing a flat linkedin-export/ folder:
     <slug>.json      one per original post, verbatim body text
     <id>.jpg         every image, plus -2 -3 for multi-image posts
     _index.json      manifest: every post, skips, warnings, editorial TODOs

   INTEGRITY
   Each post JSON carries two tamper checks over the verbatim body:
     body_sha256   hex SHA-256 of the UTF-8 bytes of the body string
                   (body_he for Hebrew posts, body_en otherwise)
     text_witness  "<charCount> chars | <first 40> ... <last 40>"
   Ingest verifies body_sha256 and rejects the bundle if a body changed after
   export. Nothing downstream may edit body_en, body_he, body_sha256 or
   text_witness. _index.json repeats both per post.

   WHAT IT DOES NOT DO
   Titles, themes and excerpts are auto-derived and marked
   "needs_editorial": true. Hebrew posts get body_he verbatim, language "he",
   english_is_machine_translation true, and body_en left EMPTY — deliberately,
   so nothing provisional can publish under your byline. Hand _index.json to
   an agent to fill those in; it needs no browser access.
   ========================================================================= */

(function () {
  'use strict';

  const CUTOFF = '2025-01-01';        // <-- change this to move the window
  const OWNER  = 'Lotan Levkowitz';   // used to detect other people's posts

  if (window.__liExport) { window.__liExport.panel.remove(); clearInterval(window.__liExport.timer); }

  // ---------- helpers ------------------------------------------------------
  const dateOf = id => new Date(Number(BigInt(String(id).match(/(\d+)/)[1]) >> 22n))
                        .toISOString().slice(0, 10);

  const isHebrew = t => (t.match(/[\u0590-\u05FF]/g) || []).length > 50;

  // Integrity: hex SHA-256 of the UTF-8 bytes of the exact body string written
  // to the JSON (body_he for Hebrew posts, body_en otherwise). Ingest verifies
  // this and rejects the bundle if a body changed after export.
  async function sha256Hex(str) {
    const bytes = new TextEncoder().encode(str);
    const buf = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
  }

  // Human-readable companion to the hash. Format is exactly:
  //   "<charCount> chars | <first 40 chars> ... <last 40 chars>"
  // Newlines collapsed to spaces so it stays one line. Lets a human eyeball
  // whether a body was truncated or swapped without recomputing anything.
  function textWitness(str) {
    const flat = str.replace(/\s+/g, ' ').trim();
    const head = clip(flat, 40);
    const tail = flat.length > 80 ? clipTail(flat, 40) : '';
    return `${str.length} chars | ${head}${tail ? ' ... ' + tail : ''}`;
  }

  const slugify = t => t.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/^-+|-+$/g, '') || 'untitled';

  function autoTitle(text) {
    const first = (text.split('\n').find(l => l.trim().length > 10) || text).trim();
    let t = first.split(/(?<=[.?!])\s/)[0].trim();
    if (t.length > 70) t = clip(t, 67).replace(/\s+\S*$/, '') + '...';
    return t.replace(/["""]/g, '');
  }

  function autoExcerpt(text) {
    const clean = text.replace(/\s+/g, ' ').trim();
    return clean.length > 220 ? clip(clean, 217).replace(/\s+\S*$/, '') + '...' : clean;
  }

  // JS string indexes are UTF-16 code units. A fixed slice can land between
  // the two units of an emoji and emit a lone surrogate. That string is valid
  // JSON and then crashes UTF-8 printers (verify-bundle.py did, on a harvest
  // warning whose cut fell inside an emoji). Back up, or step forward, so
  // every truncated string ends and starts on a code-point boundary.
  function clip(s, n) {
    s = s || '';
    if (s.length <= n) return s;
    let end = n;
    const c = s.charCodeAt(end - 1);
    if (c >= 0xD800 && c <= 0xDBFF) end -= 1;
    return s.slice(0, Math.max(0, end));
  }
  function clipTail(s, n) {
    s = s || '';
    if (s.length <= n) return s;
    let start = s.length - n;
    const c = s.charCodeAt(start);
    if (c >= 0xDC00 && c <= 0xDFFF) start += 1;
    return s.slice(start);
  }

  // ---------- store --------------------------------------------------------
  const store = new Map();   // id -> record
  const idProblems = new Set();   // containers we refused to record (ambiguous / missing id)

  // LinkedIn (2026) renders hashed class names, so everything below keys off
  // stable attributes only: aria-label, data-testid, href, src/srcset.
  const MENU_SEL   = '[aria-label^="Open control menu for post"]';
  const TEXT_SEL   = '[data-testid="expandable-text-box"]';
  const MORE_SEL   = '[data-testid="expandable-text-button"]';
  const BAR_SEL    = 'button[aria-label^="Reaction button state"], button[aria-label="Comment"], button[aria-label^="React "]';
  const URN_RE     = /urn:li:(activity|share|ugcPost):(\d{15,})/;
  const VANITY_RE  = /\/posts\/[^/?#]*-activity-(\d{15,})-/;   // /posts/<slug>-activity-<id>-xxxx
  const OWNER_SLUG = ((location.pathname.match(/\/in\/([^/]+)/) || [])[1] || 'lotanlevkowitz').toLowerCase();
  const HEADER_OTHER_RE = /\b(reposted|reshared|commented on|replied to|likes this|liked this|loves this|celebrates this|supports this|finds this|is curious about this)\b/i;
  const clicked = new WeakSet();

  const precedes = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  const textOf   = el => (el ? (el.innerText ?? el.textContent ?? '') : '');
  const safeDecode = s => { try { return decodeURIComponent(s); } catch (e) { return s; } };

  // One container per post: climb from the post's control-menu button to the
  // largest ancestor that still holds exactly one such button (and at most one
  // analytics id). Stops at the per-post lazy-mount wrapper or the page column.
  function findContainers() {
    const out = new Set();
    document.querySelectorAll(MENU_SEL).forEach(btn => {
      let el = btn;
      while (el.parentElement && !el.hasAttribute('data-lazy-mount-id')) {
        const p = el.parentElement;
        if (p === document.body || p.matches('main, [role="main"]')) break;
        if (p.querySelectorAll(MENU_SEL).length > 1) break;
        if (analyticsIds(p).size > 1) break;
        el = p;
      }
      out.add(el);
    });
    return [...out];
  }

  // urn from the URL PATH only. Query strings are ignored on purpose: e.g. the
  // "Boost" link carries content=urn:li:share:<other number> for the same post.
  function hrefUrn(a) {
    const h = safeDecode((a.getAttribute('href') || '').split(/[?#]/)[0]);
    let m = h.match(URN_RE);
    if (m) return { type: m[1], id: m[2], href: h };
    m = h.match(VANITY_RE);
    return m ? { type: 'activity', id: m[1], href: h } : null;
  }

  function analyticsIds(scope) {
    const ids = new Map();
    scope.querySelectorAll('a[href*="/analytics/"]').forEach(a => {
      const u = hrefUrn(a); if (u) ids.set(u.id, u);
    });
    return ids;
  }

  // highest ancestor of node (below root) that does not contain `avoid`
  function climbAway(node, root, avoid) {
    let el = node;
    while (el.parentElement && el.parentElement !== root && !(avoid && el.parentElement.contains(avoid))) el = el.parentElement;
    return el;
  }

  // label of an avatar/profile link: "View Jane Doe’s profile" / "View company: Acme"
  function profileName(el) {
    const l = (el.getAttribute('aria-label') || el.getAttribute('alt') || '').trim();
    let m = l.match(/^View (.+?)[’']s profile/i); if (m) return m[1].trim();
    m = l.match(/^View company:\s*(.+)$/i);          if (m) return m[1].trim();
    return '';
  }
  const isOwnerLink = a => {
    const h = (a.getAttribute('href') || '').toLowerCase();
    return h.includes('/in/' + OWNER_SLUG + '/') || h.endsWith('/in/' + OWNER_SLUG);
  };

  // largest served size: biggest srcset candidate, else src. URLs are signed
  // per size, so they are never rewritten.
  function bestSrc(img) {
    let best = null, bw = -1;
    (img.getAttribute('srcset') || '').split(/,\s*(?=https?:\/\/)/).forEach(c => {
      const [u, d] = c.trim().split(/\s+/);
      const w = parseInt(d, 10) || 0;
      if (u && w >= bw) { bw = w; best = u; }
    });
    if (!best) {
      best = img.getAttribute('src') || img.currentSrc || '';
      bw = parseInt((best.match(/shrink_(\d+)/) || [])[1] || '0', 10);
    }
    return { url: best, w: bw };
  }

  function boxText(box) {
    if (!box) return '';
    let t = textOf(box);
    // the "… more" button sits INSIDE the text box; drop its label if it trails
    box.querySelectorAll(MORE_SEL).forEach(b => {
      const bt = textOf(b).trim();
      const tt = t.replace(/\s+$/, '');
      if (bt && tt.endsWith(bt)) t = tt.slice(0, -bt.length);
    });
    t = t.replace(/\s*(?:…|\.\.\.)\s*(?:see\s+)?more\s*$/i, '')
         .replace(/\s*(?:…\s*)?see\s+(?:more|less)\s*$/i, '');
    return t.trim();
  }

  // Everything below reads from ONE container element.
  function extract(root) {
    const menu = root.querySelector(MENU_SEL);
    const menuAuthor = ((menu && menu.getAttribute('aria-label')) || '')
                         .replace(/^Open control menu for post\s*(by\s*)?/i, '').trim();

    // social bar = start of reactions/comments; nothing after it is post content
    const bar = root.querySelector(BAR_SEL);
    const inBody = el => !bar || precedes(el, bar);

    const boxes  = [...root.querySelectorAll(TEXT_SEL)].filter(inBody);
    const ownBox = boxes[0] || null;            // post commentary precedes any reshared post
    const anchor = ownBox || menu || root;

    // nested / reshared posts: later text boxes, or avatars of other people
    // after the commentary. Each is widened to its own subtree.
    const nested = [];
    const inNested = el => nested.some(n => n === el || n.contains(el));
    const addNested = node => { if (!inNested(node)) nested.push(climbAway(node, root, anchor)); };
    boxes.slice(1).forEach(addNested);
    const nestedAuthors = [];
    root.querySelectorAll('a[href*="/in/"], a[href*="/company/"], img[alt^="View "]').forEach(el => {
      if (!inBody(el) || boxes.some(b => b.contains(el))) return;
      if (anchor !== root && !precedes(anchor, el)) return;
      const a = el.closest('a') || el;
      if (a.tagName === 'A' && !a.querySelector('img, svg') && el.tagName !== 'IMG') return; // text links only
      if (a.tagName === 'A' && isOwnerLink(a)) return;
      const name = profileName(el) || profileName(a);
      if (!name || name === OWNER) return;
      nestedAuthors.push(name);
      addNested(el);
    });
    const own = el => inBody(el) && !inNested(el) && !boxes.some(b => b !== ownBox && b.contains(el));

    // ---- id: analytics link first, then the post's own permalink ----------
    let id = null, urn = null;
    const ana = analyticsIds(root);
    if (ana.size === 1) {
      const u = [...ana.values()][0]; id = u.id; urn = `urn:li:${u.type}:${u.id}`;
    } else if (ana.size === 0) {
      const perma = new Map();
      root.querySelectorAll('a[href]').forEach(a => {
        if (!own(a)) return;
        const u = hrefUrn(a); if (u && !/\/analytics\//.test(u.href)) perma.set(u.id, u);
      });
      const acts = [...perma.values()].filter(u => u.type === 'activity');
      const pick = acts.length === 1 ? acts[0] : (acts.length === 0 && perma.size === 1 ? [...perma.values()][0] : null);
      if (pick) { id = pick.id; urn = `urn:li:${pick.type}:${pick.id}`; }
    }
    if (!id) return { problem: (ana.size > 1 ? 'ambiguous analytics ids ' + [...ana.keys()].join('/') : 'no activity id') +
                               ` | by ${menuAuthor || '?'} | ${clip(boxText(ownBox).replace(/\s+/g, ' '), 50)}` };

    // other activity permalinks inside the body = a reshared post
    root.querySelectorAll('a[href]').forEach(a => {
      if (!inBody(a) || inNested(a)) return;
      const u = hrefUrn(a);
      if (u && u.type === 'activity' && u.id !== id && !/\/analytics\//.test(u.href)) addNested(a);
    });

    // ---- header / author ---------------------------------------------------
    let head = '';
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n && head.length < 400; n = tw.nextNode()) {
      if (anchor !== root && (anchor.contains(n) || precedes(anchor, n))) break;
      head += n.nodeValue + ' ';
    }
    const actorEl  = [...root.querySelectorAll('img[alt^="View "], a[aria-label^="View "]')]
                       .find(e => profileName(e) && (anchor === root || precedes(e, anchor)));
    const actor    = actorEl ? profileName(actorEl) : menuAuthor;
    const repostHeader = HEADER_OTHER_RE.test(head);
    const byOther  = repostHeader || (!!menuAuthor && menuAuthor !== OWNER) || (!!actor && actor !== OWNER);

    // ---- text --------------------------------------------------------------
    let text = boxText(ownBox && own(ownBox) ? ownBox : null);
    if (!ownBox) {
      const tc = [...root.querySelectorAll('[componentkey^="translatable-commentary"]')].find(own);
      if (tc) text = textOf(tc).trim();
    }

    // ---- media (own content only) -----------------------------------------
    const seen = new Set(), imgs = [];
    root.querySelectorAll('img').forEach(img => {
      if (!own(img)) return;
      const { url, w } = bestSrc(img);
      const all = (img.getAttribute('src') || '') + ' ' + (img.getAttribute('srcset') || '');
      if (!/media\.licdn\.com/.test(url) || !/\/feedshare-/.test(all)) return;   // not post media
      const link = img.closest('a[href]');
      if (link) {                                                               // article / link-preview card
        const h = link.getAttribute('href') || '';
        if (/\/safety\/go|\/redir\/|\/pulse\//.test(h) || (/^https?:\/\//.test(h) && !/^https?:\/\/([a-z0-9-]+\.)*linkedin\.com\//i.test(h))) return;
      }
      const key = (url.match(/\/image\/v2\/([^/]+)\//) || [])[1] || url.split('?')[0];
      if (seen.has(key)) return;
      seen.add(key); imgs.push({ url, w });
    });
    const vid    = [...root.querySelectorAll('video')].find(own);
    const poster = vid ? (vid.getAttribute('poster') || null) : null;
    const hasDoc = [...root.querySelectorAll('iframe')].some(own) ||
      [...root.querySelectorAll('[data-testid], [aria-label], [title]')].some(e => own(e) &&
        /document|pdf/i.test((e.getAttribute('data-testid') || '') + ' ' + (e.getAttribute('aria-label') || '') + ' ' + (e.getAttribute('title') || ''))) ||
      [...root.querySelectorAll('span, div, p')].some(e => own(e) && !e.children.length && !(ownBox && ownBox.contains(e)) &&
        /^\s*\d+\s+pages?\s*$/i.test(e.textContent || ''));

    const isNested = nested.length > 0;
    return {
      id, urn, actor: menuAuthor || actor, text,
      imgs, poster, isVideo: !!vid && !imgs.length, hasDoc,
      byOther, repostHeader, nestedAuthors,
      repost: byOther || isNested,
      quoteRepost: !byOther && isNested && text.length > 0
    };
  }

  function harvest() {
    // expand truncated text first ("… more" button inside each text box)
    document.querySelectorAll(MORE_SEL).forEach(b => {
      if (clicked.has(b) || !/more/i.test(textOf(b))) return;
      clicked.add(b);
      try { b.click(); } catch (e) {}
    });

    findContainers().forEach(root => {
      const r = extract(root);
      if (r.problem) { idProblems.add(r.problem); return; }
      const id = r.id;
      if (!/^\d+$/.test(id)) return;

      const imgs   = r.imgs.map(i => i.url);
      const poster = r.poster;
      const assets = imgs.length ? imgs : (poster ? [poster] : []);
      const assetW = imgs.length ? r.imgs.reduce((s, i) => s + i.w, 0) : 0;
      const prev   = store.get(id);

      // flags are sticky: once any render shows it is a repost/doc, it stays so
      const byOther = r.byOther || !!(prev && prev.byOther);
      const repost  = r.repost  || !!(prev && prev.repost);
      const flags = {
        byOther, repost,
        quoteRepost: repost && !byOther && (r.quoteRepost || !!(prev && prev.quoteRepost)),
        hasDoc: r.hasDoc || !!(prev && prev.hasDoc)
      };

      // keep the richest version we have ever seen of this post
      if (!prev || r.text.length > prev.text.length || assets.length > prev.assets.length ||
          (assets.length === prev.assets.length && assetW > (prev.assetW || 0))) {
        const keepAssets = prev && (prev.assets.length > assets.length ||
                           (prev.assets.length === assets.length && (prev.assetW || 0) >= assetW));
        store.set(id, {
          id, urn: r.urn, actor: r.actor,
          date: dateOf(id),
          text: (prev && prev.text.length > r.text.length) ? prev.text : r.text,
          assets: keepAssets ? prev.assets : assets,
          assetW: keepAssets ? prev.assetW : assetW,
          isVideo: keepAssets ? prev.isVideo : (!!r.isVideo),
          ...flags
        });
      } else {
        Object.assign(prev, flags);
      }
    });
    return store.size;
  }

  // ---------- zip (store method, no deps) ----------------------------------
  const crcTable = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  const crc32 = u8 => { let c = 0xFFFFFFFF; for (let i = 0; i < u8.length; i++) c = crcTable[(c ^ u8[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };

  function makeZip(files) {
    const enc = new TextEncoder(), chunks = [], central = [];
    let offset = 0;
    const u16 = v => { const b = new Uint8Array(2); b[0] = v & 255; b[1] = (v >> 8) & 255; return b; };
    const u32 = v => { const b = new Uint8Array(4); b[0] = v & 255; b[1] = (v >>> 8) & 255; b[2] = (v >>> 16) & 255; b[3] = (v >>> 24) & 255; return b; };
    const cat = a => { let n = 0; a.forEach(x => n += x.length); const o = new Uint8Array(n); let p = 0; a.forEach(x => { o.set(x, p); p += x.length; }); return o; };

    for (const f of files) {
      const name = enc.encode(f.name), data = f.bytes, crc = crc32(data);
      const lfh = cat([u32(0x04034b50), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
                       u32(crc), u32(data.length), u32(data.length),
                       u16(name.length), u16(0), name]);
      chunks.push(lfh, data);
      central.push(cat([u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
                        u32(crc), u32(data.length), u32(data.length),
                        u16(name.length), u16(0), u16(0), u16(0), u16(0),
                        u32(0), u32(offset), name]));
      offset += lfh.length + data.length;
    }
    const cd = cat(central);
    const eocd = cat([u32(0x06054b50), u16(0), u16(0), u16(files.length), u16(files.length),
                      u32(cd.length), u32(offset), u16(0)]);
    return new Blob([cat(chunks), cd, eocd], { type: 'application/zip' });
  }

  // ---------- build --------------------------------------------------------
  async function build(statusFn) {
    const enc = new TextEncoder();
    const all = [...store.values()].sort((a, b) => b.date.localeCompare(a.date));
    const keep = all.filter(p => p.date >= CUTOFF && !p.repost && p.text.length > 0);
    const skipped = all.filter(p => p.date >= CUTOFF && (p.repost || !p.text.length))
                       .map(p => p.quoteRepost
                         ? { id: p.id, date: p.date, reason: 'quote-repost', needs_review: true,
                             linkedin_url: `https://www.linkedin.com/feed/update/${p.urn || 'urn:li:activity:' + p.id}/`,
                             commentary: p.text }
                         : { id: p.id, date: p.date, reason: p.repost ? 'repost / not authored by owner' : 'no body text' });

    const files = [], index = [], warnings = [];
    idProblems.forEach(m => warnings.push(`harvest: skipped a post container (${m})`));
    const usedSlugs = new Set();
    let done = 0;

    for (const p of keep) {
      statusFn(`fetching images ${++done}/${keep.length}`);
      const title = autoTitle(p.text);
      let slug = slugify(title);
      while (usedSlugs.has(slug)) slug = slug + '-' + p.id.slice(-4);
      usedSlugs.add(slug);

      const he = isHebrew(p.text);
      const savedImgs = [];

      for (let i = 0; i < p.assets.length; i++) {
        const fname = p.id + (i === 0 ? '' : '-' + (i + 1)) + '.jpg';
        try {
          const r = await fetch(p.assets[i]);
          if (!r.ok) { warnings.push(`${p.id} image ${i + 1}: HTTP ${r.status}`); continue; }
          const bytes = new Uint8Array(await r.arrayBuffer());
          files.push({ name: 'linkedin-export/' + fname, bytes });
          savedImgs.push(fname);
        } catch (e) { warnings.push(`${p.id} image ${i + 1}: ${e.message}`); }
      }

      if (p.isVideo)  warnings.push(`${p.id} (${p.date}) is a VIDEO post - only the poster frame was saved`);
      if (p.hasDoc)   warnings.push(`${p.id} (${p.date}) is a DOCUMENT/carousel - slides were NOT exported, check manually`);

      // the body that carries the verbatim post text, and is what gets hashed
      const canonicalBody = he ? p.text : p.text;

      const obj = {
        title,
        date: p.date,
        theme: '',
        linkedin_url: `https://www.linkedin.com/feed/update/${p.urn || 'urn:li:activity:' + p.id}/`,
        excerpt: autoExcerpt(p.text),
        body_en: he ? '' : p.text,
        body_he: he ? p.text : '',
        language: he ? 'he' : 'en',
        english_is_machine_translation: he,
        body_sha256: await sha256Hex(canonicalBody),
        text_witness: textWitness(canonicalBody),
        needs_editorial: true
      };
      if (savedImgs.length) obj.image = savedImgs[0];
      if (savedImgs.length > 1) obj.figures = savedImgs.slice(1);

      files.push({ name: `linkedin-export/${slug}.json`, bytes: enc.encode(JSON.stringify(obj, null, 2)) });
      index.push({ file: slug + '.json', id: p.id, date: p.date, language: obj.language,
                   images: savedImgs.length, is_video: p.isVideo, is_document: p.hasDoc,
                   auto_title: title,
                   body_sha256: obj.body_sha256, text_witness: obj.text_witness });
    }

    const dates = keep.map(p => p.date).sort();
    const gaps = [];
    for (let i = 1; i < dates.length; i++) {
      const d = (new Date(dates[i]) - new Date(dates[i - 1])) / 86400000;
      if (d > 21) gaps.push(`${dates[i - 1]} -> ${dates[i]} (${Math.round(d)} days)`);
    }

    const manifest = {
      generated: new Date().toISOString(),
      cutoff: CUTOFF,
      total_exported: keep.length,
      date_range: dates.length ? [dates[0], dates[dates.length - 1]] : null,
      suspicious_gaps: gaps,
      skipped,
      warnings,
      editorial_todo: 'title/theme/excerpt are auto-generated. body_en is EMPTY for Hebrew posts by design.',
      posts: index
    };
    files.push({ name: 'linkedin-export/_index.json', bytes: enc.encode(JSON.stringify(manifest, null, 2)) });

    return { blob: makeZip(files), manifest, fileCount: files.length };
  }

  // ---------- panel --------------------------------------------------------
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;top:16px;left:16px;z-index:2147483647;background:#111;color:#eee;' +
    'font:13px/1.5 -apple-system,system-ui,sans-serif;padding:14px 16px;border-radius:10px;' +
    'box-shadow:0 6px 24px rgba(0,0,0,.4);width:290px;';
  panel.innerHTML =
    '<div style="font-weight:700;margin-bottom:8px">LinkedIn export</div>' +
    '<div id="lex-stat" style="margin-bottom:6px">collected: 0</div>' +
    '<div id="lex-old" style="margin-bottom:6px;color:#9cf">oldest: -</div>' +
    '<div id="lex-hint" style="margin-bottom:10px;color:#fc6">scroll down the page yourself</div>' +
    '<button id="lex-go" style="width:100%;padding:10px;font-weight:700;background:#0a66c2;color:#fff;' +
    'border:0;border-radius:6px;cursor:pointer">BUILD + DOWNLOAD ZIP</button>' +
    '<div id="lex-log" style="margin-top:8px;color:#aaa;font-size:11px"></div>';
  document.body.appendChild(panel);

  const $ = id => panel.querySelector(id);
  const setLog = m => { $('#lex-log').textContent = m; };

  const timer = setInterval(() => {
    const n = harvest();
    const ds = [...store.values()].map(v => v.date).sort();
    const oldest = ds[0] || '-';
    $('#lex-stat').textContent = `collected: ${n}`;
    $('#lex-old').textContent  = `oldest: ${oldest}`;
    if (oldest !== '-' && oldest < CUTOFF) {
      $('#lex-hint').textContent = 'CUTOFF REACHED - safe to build';
      $('#lex-hint').style.color = '#6f6';
    }
  }, 700);

  $('#lex-go').addEventListener('click', async () => {
    $('#lex-go').disabled = true;
    try {
      const { blob, manifest, fileCount } = await build(setLog);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'linkedin-export.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 120000);
      setLog(`done: ${manifest.total_exported} posts, ${fileCount} files, ${Math.round(blob.size / 1024)} KB`);
      console.log('[linkedin-export] manifest:', manifest);
      if (manifest.suspicious_gaps.length)
        console.warn('[linkedin-export] GAPS - scroll those stretches again and rebuild:', manifest.suspicious_gaps);
    } catch (e) {
      setLog('ERROR: ' + e.message);
      console.error(e);
    }
    $('#lex-go').disabled = false;
  });

  window.__liExport = { store, panel, timer, harvest, build };
  console.log('[linkedin-export] ready. Scroll down; panel tracks progress. Cutoff =', CUTOFF);
})();


