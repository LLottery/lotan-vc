#!/usr/bin/env python3
"""
Tell IndexNow about URLs that just changed on lotan.vc.

The publish workflow runs this after main is mirrored onto gh-pages. Failure
is non-fatal: the workflow step uses continue-on-error, and this script
prints the reason before exiting 1.

    python3 tools/indexnow.py                  # URLs from INDEXNOW_BEFORE..SHA
    python3 tools/indexnow.py https://lotan.vc/w/example.html
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "lotan.vc"
ENDPOINT = "https://api.indexnow.org/indexnow"
ATTEMPTS = 6
PAUSE = 15


def find_key():
    for name in sorted(os.listdir(ROOT)):
        if not re.fullmatch(r"[0-9a-fA-F-]{8,128}\.txt", name):
            continue
        key = name[: -len(".txt")]
        body = open(os.path.join(ROOT, name), encoding="utf-8").read().strip()
        if body == key:
            return key
    sys.exit("error: no IndexNow key file at the repo root")


def to_url(path):
    path = path.replace(os.sep, "/")
    if path == "index.html":
        return f"https://{HOST}/"
    if path == "essays/index.html":
        return f"https://{HOST}/essays/"
    if path == "w/index.html":
        return f"https://{HOST}/w/"
    if path.startswith("essays/") and path.endswith(".html") and path != "essays/index.html":
        return f"https://{HOST}/{path}"
    if path.startswith("w/") and path.endswith(".html") and path != "w/index.html":
        return f"https://{HOST}/{path}"
    return None


def changed_paths():
    before = os.environ.get("INDEXNOW_BEFORE", "").strip()
    sha = os.environ.get("INDEXNOW_SHA", "HEAD").strip() or "HEAD"
    if before and set(before) != {"0"}:
        spec = [before, sha]
    else:
        # workflow_dispatch, or the first push (before is all zeros).
        spec = [f"{sha}^", sha]
    r = subprocess.run(
        ["git", "diff", "--name-only"] + spec,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode:
        show = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", sha],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if show.returncode:
            print(r.stderr.strip() or show.stderr.strip() or "could not list changed files")
            return []
        return [p for p in show.stdout.splitlines() if p.strip()]
    return [p for p in r.stdout.splitlines() if p.strip()]


def changed_urls():
    urls = []
    for path in changed_paths():
        url = to_url(path)
        if url and url not in urls:
            urls.append(url)
    return urls


def ping(urls):
    key = find_key()
    payload = json.dumps(
        {
            "host": HOST,
            "key": key,
            "keyLocation": f"https://{HOST}/{key}.txt",
            "urlList": urls,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    last = "no response"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                print(f"IndexNow {res.status} for {len(urls)} URL(s)")
                return 0
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code} {body}".strip()
        except Exception as e:
            last = str(e)
        print(f"IndexNow attempt {attempt}/{ATTEMPTS} failed: {last}")
        if attempt < ATTEMPTS:
            time.sleep(PAUSE)
    print(f"IndexNow gave up: {last}")
    return 1


def main():
    urls = sys.argv[1:] or changed_urls()
    if not urls:
        print("IndexNow: no changed URLs")
        return 0
    # The key file has to be one this repo will publish. Refuse a typo'd URL.
    for url in urls:
        if not url.startswith(f"https://{HOST}/"):
            print(f"refusing URL outside {HOST}: {url}")
            return 1
    print("IndexNow URLs:")
    for url in urls:
        print(f"  {url}")
    return ping(urls)


if __name__ == "__main__":
    sys.exit(main())
