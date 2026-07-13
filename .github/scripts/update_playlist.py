#!/usr/bin/env python3
"""Refresh JIO tokens (both __hdnea__ and hdntl) and append fresh Zee m3u."""
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


def extract_tokens(m3u_text: str) -> dict | None:
    """Parse M3U, extract tokens from any URL or #EXTHTTP header.
    Returns dict with 'hdnea' and/or 'hdntl' tokens if found, or None."""
    tokens = {}
    
    for line in m3u_text.splitlines():
        line = line.rstrip()
        
        # Check for tokens in #EXTHTTP header
        if line.startswith("#EXTHTTP:"):
            try:
                json_str = line[len("#EXTHTTP:"):]
                data = json.loads(json_str)
                cookie_value = data.get("Cookie") or data.get("cookie")
                if cookie_value:
                    # Look for __hdnea__ token
                    m = re.search(r"__hdnea__=[^~&\s\"]+", cookie_value)
                    if m:
                        tokens['hdnea'] = m.group(0)
                    # Look for hdntl token
                    m = re.search(r"hdntl=[^~&\s\"~]*(?:~[^~&\s\"~]*)*", cookie_value)
                    if m:
                        tokens['hdntl'] = m.group(0)
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Check for tokens in URL query string
        if line.startswith(("http://", "https://")):
            m = re.search(r"__hdnea__=[^|&\s\"]+", line)
            if m and 'hdnea' not in tokens:
                tokens['hdnea'] = m.group(0)
            m = re.search(r"hdntl=[^&\s\"]+", line)
            if m and 'hdntl' not in tokens:
                tokens['hdntl'] = m.group(0)
    
    return tokens if tokens else None


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


def refresh_streams(m3u: str, tokens: dict | None) -> list[str]:
    """Return output lines for entries, tokens refreshed if available.
    If tokens is None, pass through entries as-is."""
    out = []
    for meta, url in iter_blocks(m3u):
        if url is None:
            continue  # skip entries without URLs
        
        # Process metadata lines, refreshing tokens in any #EXTHTTP / #KODIPROP headers
        for m in meta:
            if tokens and m.startswith("#EXTHTTP:"):
                try:
                    json_str = m[len("#EXTHTTP:"):]
                    data = json.loads(json_str)
                    # Normalize to "Cookie" (capital C)
                    cookie_value = data.get("Cookie") or data.get("cookie") or ""
                    
                    # Refresh __hdnea__ token if we have one
                    if 'hdnea' in tokens:
                        cookie_value = re.sub(r"__hdnea__=[^~&\s\"]+", tokens['hdnea'], cookie_value)
                    
                    # Refresh hdntl token if we have one
                    if 'hdntl' in tokens:
                        cookie_value = re.sub(r"hdntl=[^~&\s\"~]*(?:~[^~&\s\"~]*)*", tokens['hdntl'], cookie_value)
                    
                    if cookie_value:
                        data["Cookie"] = cookie_value
                    
                    # Remove lowercase "cookie" if it exists to avoid duplicates
                    data.pop("cookie", None)
                    m = f"#EXTHTTP:{json.dumps(data)}"
                except (json.JSONDecodeError, KeyError):
                    # If parsing fails, try simple regex replacement
                    if "__hdnea__=" in m and 'hdnea' in tokens:
                        m = re.sub(r"__hdnea__=[^\"}\s]+", tokens['hdnea'], m)
                    if "hdntl=" in m and 'hdntl' in tokens:
                        m = re.sub(r"hdntl=[^\"}\s]+", tokens['hdntl'], m)
            elif tokens:
                # Refresh tokens in other headers
                if "__hdnea__=" in m and 'hdnea' in tokens:
                    m = re.sub(r"__hdnea__=[^\"}\s]+", tokens['hdnea'], m)
                if "hdntl=" in m and 'hdntl' in tokens:
                    m = re.sub(r"hdntl=[^\"}\s]+", tokens['hdntl'], m)
            
            out.append(m)
        
        # Clean URL: refresh tokens if available
        if tokens:
            url_out = url
            # Refresh __hdnea__ in URL if present and we have a token
            if 'hdnea' in tokens and "__hdnea__=" in url_out:
                url_out = re.sub(r"__hdnea__=[^&\s\"]+", tokens['hdnea'], url_out)
            # Refresh hdntl in URL if present and we have a token
            if 'hdntl' in tokens and "hdntl=" in url_out:
                url_out = re.sub(r"hdntl=[^&\s\"]+", tokens['hdntl'], url_out)
            out.append(url_out)
        else:
            # No tokens available, pass URL as-is
            out.append(url)
    
    return out


def main() -> None:
    print("1) Fetch JIO M3U + extract tokens")
    jio_source = fetch(JIO_SOURCE)
    jio_tokens = extract_tokens(jio_source)
    if jio_tokens:
        print(f"   -> Tokens found: {list(jio_tokens.keys())}")
        for token_type, token_val in jio_tokens.items():
            print(f"      {token_type}: {token_val[:60]}...")
    else:
        print("   -> No tokens found, will pass JIO entries as-is")

    print("2) Process JIO entries")
    jio_lines = refresh_streams(jio_source, jio_tokens)
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
