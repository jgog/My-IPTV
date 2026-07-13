#!/usr/bin/env python3
"""Refresh JIO __hdnea__ cookies and append fresh Zee m3u."""
import json
import re
import sys
import urllib.request
from pathlib import Path

JIO_SOURCE = "https://fancy-morning-a287.poonamchouhan076.workers.dev"
ZEE_SOURCE = "https://join-vaathala1-for-more.vodep39240327.workers.dev/zee5.m3u"
OUT = Path("playlist.m3u")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def extract_jio_token(jio_m3u_text: str) -> str:
    """Parse M3U, extract the __hdnea__ token from any URL or #EXTHTTP header.
    All entries share the same token (wildcard ACL), so first hit wins."""
    for line in jio_m3u_text.splitlines():
        line = line.rstrip()
        
        # Check for token in #EXTHTTP header
        if line.startswith("#EXTHTTP:"):
            try:
                # Parse JSON from #EXTHTTP: header
                json_str = line[len("#EXTHTTP:"):]
                data = json.loads(json_str)
                # Token might be in Cookie header
                if "Cookie" in data:
                    m = re.search(r"__hdnea__=[^~&\s\"]+", data["Cookie"])
                    if m:
                        return m.group(0)
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Check for token in URL query string
        if line.startswith(("http://", "https://")):
            m = re.search(r"__hdnea__=[^|&\s\"]+", line)
            if m:
                return m.group(0)
    
    raise RuntimeError("No __hdnea__ token found in JIO M3U")


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


def refresh_jio(jio_m3u: str, token: str) -> list[str]:
    """Return output lines for JIO entries (.m3u8 or .mpd), token refreshed."""
    out = []
    for meta, url in iter_blocks(jio_m3u):
        if url is None:
            continue  # skip entries without URLs
        
        # Process metadata lines, refreshing token in any #EXTHTTP / #KODIPROP headers
        for m in meta:
            if m.startswith("#EXTHTTP:"):
                try:
                    # Parse and update Cookie header with new token
                    json_str = m[len("#EXTHTTP:"):]
                    data = json.loads(json_str)
                    if "Cookie" in data:
                        data["Cookie"] = re.sub(r"__hdnea__=[^~&\s\"]+", token, data["Cookie"])
                    m = f"#EXTHTTP:{json.dumps(data)}"
                except (json.JSONDecodeError, KeyError):
                    # If parsing fails, try simple regex replacement
                    if "__hdnea__=" in m:
                        m = re.sub(r"__hdnea__=[^\"}\s]+", token, m)
            elif "__hdnea__=" in m:
                # Refresh token in other headers that carry it
                m = re.sub(r"__hdnea__=[^\"}\s]+", token, m)
            
            out.append(m)
        
        # Clean URL: drop any existing __hdnea__ query param, append fresh token
        base_url = url.split("?", 1)[0]
        # Preserve other query params if present
        if "?" in url:
            other_params = url.split("?", 1)[1]
            # Remove __hdnea__ if it's in other_params
            other_params = re.sub(r"__hdnea__=[^&]+&?", "", other_params).rstrip("&")
            if other_params:
                out.append(f"{base_url}?{other_params}&{token}")
            else:
                out.append(f"{base_url}?{token}")
        else:
            out.append(f"{base_url}?{token}")
    
    return out


def main() -> None:
    print("1) Fetch JIO M3U + extract token")
    jio_source = fetch(JIO_SOURCE)
    jio_token = extract_jio_token(jio_source)
    print(f"   -> {jio_token[:60]}...")

    print("2) Refresh JIO entries")
    jio_lines = refresh_jio(jio_source, jio_token)
    print(f"   -> {sum(1 for l in jio_lines if l.startswith(('http://','https://')))} JIO channels")

    print("3) Fetch fresh Zee m3u")
    zee = fetch(ZEE_SOURCE)
    if not zee.lstrip().startswith("#EXTM3U"):
        print("   WARNING: Zee source doesn't look like an M3U")
    zee_lines = [l for l in zee.splitlines() if not l.startswith("#EXTM3U")]

    print("4) Write output")
    OUT.write_text("\n".join(["#EXTM3U", *jio_lines, *zee_lines]) + "\n")
    print(f"   -> wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
