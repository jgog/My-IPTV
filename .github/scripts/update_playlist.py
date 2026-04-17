#!/usr/bin/env python3
"""Refresh JIO __hdnea__ cookies and append fresh Zee m3u."""
import json
import re
import sys
import urllib.request
from pathlib import Path

JIO_SOURCE = "https://jo-json.vodep39240327.workers.dev"
ZEE_SOURCE = "https://join-vaathala1-for-more.vodep39240327.workers.dev/zee5.m3u"
OUT = Path("playlist.m3u")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def extract_jio_token(jio_json_text: str) -> str:
    """Parse JSON, pull the __hdnea__ query param from any entry's URL.
    All entries share the same token (wildcard ACL), so first hit wins."""
    data = json.loads(jio_json_text)
    for entry in data.values():
        url = entry.get("url", "")
        # URL format: ...mpd?__hdnea__=TOKEN|cookie=...  — stop at | & space quote
        m = re.search(r"__hdnea__=[^|&\s\"]+", url)
        if m:
            return m.group(0)
    raise RuntimeError("No __hdnea__ token found in JIO JSON")


def iter_blocks(m3u_text: str):
    """Yield (metadata_lines, url_line_or_None) per #EXTINF block."""
    block = []
    for line in m3u_text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            if block:
                yield block, None
            block = [line]
        elif line.startswith(("http://", "https://")):
            yield block, line
            block = []
        elif block:
            block.append(line)
    if block:
        yield block, None


def refresh_jio(base_m3u: str, token: str) -> list[str]:
    """Return output lines for JIO entries only (.mpd), token refreshed."""
    out = []
    for meta, url in iter_blocks(base_m3u):
        if url is None or ".mpd" not in url:
            continue  # drop Zee (.m3u8) entries carried over from last run
        for m in meta:
            # Refresh token inside any #EXTHTTP / #KODIPROP line that carries it
            if "__hdnea__=" in m:
                m = re.sub(r"__hdnea__=[^\"}\s]+", token, m)
            out.append(m)
        # Clean URL: drop any existing query, append fresh token
        out.append(f"{url.split('?', 1)[0]}?{token}")
    return out


def main() -> None:
    print("1) Fetch JIO JSON + extract token")
    jio_token = extract_jio_token(fetch(JIO_SOURCE))
    print(f"   -> {jio_token[:60]}...")

    print("2) Load existing playlist as JIO base")
    if not OUT.exists() or OUT.stat().st_size == 0:
        sys.exit(f"ERROR: {OUT} is missing/empty")
    base = OUT.read_text()

    print("3) Refresh JIO entries")
    jio_lines = refresh_jio(base, jio_token)
    print(f"   -> {sum(1 for l in jio_lines if l.startswith(('http://','https://')))} JIO channels")

    print("4) Fetch fresh Zee m3u")
    zee = fetch(ZEE_SOURCE)
    if not zee.lstrip().startswith("#EXTM3U"):
        print("   WARNING: Zee source doesn't look like an M3U")
    zee_lines = [l for l in zee.splitlines() if not l.startswith("#EXTM3U")]

    print("5) Write output")
    OUT.write_text("\n".join(["#EXTM3U", *jio_lines, *zee_lines]) + "\n")
    print(f"   -> wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
