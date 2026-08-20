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
    const head = flat.slice(0, 40);
    const tail = flat.length > 80 ? flat.slice(-40) : '';
    return `${str.length} chars | ${head}${tail ? ' ... ' + tail : ''}`;
  }

  const slugify = t => t.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/^-+|-+$/g, '') || 'untitled';

  function autoTitle(text) {
    const first = (text.split('\n').find(l => l.trim().length > 10) || text).trim();
    let t = first.split(/(?<=[.?!])\s/)[0].trim();
    if (t.length > 70) t = t.slice(0, 67).replace(/\s+\S*$/, '') + '...';
    return t.replace(/["""]/g, '');
  }

  function autoExcerpt(text) {
    const clean = text.replace(/\s+/g, ' ').trim();
    return clean.length > 220 ? clean.slice(0, 217).replace(/\s+\S*$/, '') + '...' : clean;
  }

  // ---------- store --------------------------------------------------------
  const store = new Map();   // id -> record

  function harvest() {
    // expand truncated text first
    document.querySelectorAll('.feed-shared-inline-show-more-text__see-more-less-toggle')
      .forEach(b => { if (/more/i.test(b.innerText || '')) { try { b.click(); } catch (e) {} } });

    document.querySelectorAll('div.feed-shared-update-v2[data-urn]').forEach(root => {
      const urn = root.getAttribute('data-urn');
      const id  = urn.split(':').pop();
      if (!/^\d+$/.test(id)) return;

      const head   = (root.innerText || '').slice(0, 220);
      const actor  = (root.querySelector('.update-components-actor__title')?.innerText || '')
                       .trim().split('\n')[0];
      const repost = /reposted this/i.test(head) || (actor && actor !== OWNER);

      const textEl = root.querySelector('.update-components-text');
      let text = textEl ? textEl.innerText : '';
      text = text.replace(/\s*…?\s*(see\s+)?(less|more)\s*$/i, '').trim();

      const imgs = [...root.querySelectorAll('.update-components-image img')]
                     .map(i => i.currentSrc || i.src).filter(Boolean);
      const vid    = root.querySelector('video');
      const poster = vid ? vid.getAttribute('poster') : null;
      const hasDoc = !!root.querySelector('.update-components-document');

      const assets = imgs.length ? imgs : (poster ? [poster] : []);
      const prev   = store.get(id);

      // keep the richest version we have ever seen of this post
      if (!prev || text.length > prev.text.length || assets.length > prev.assets.length) {
        store.set(id, {
          id, actor, repost,
          date: dateOf(id),
          text: (prev && prev.text.length > text.length) ? prev.text : text,
          assets: (prev && prev.assets.length > assets.length) ? prev.assets : assets,
          isVideo: !!poster && !imgs.length,
          hasDoc
        });
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
                       .map(p => ({ id: p.id, date: p.date, reason: p.repost ? 'repost / not authored by owner' : 'no body text' }));

    const files = [], index = [], warnings = [];
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
        linkedin_url: `https://www.linkedin.com/feed/update/urn:li:activity:${p.id}/`,
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
