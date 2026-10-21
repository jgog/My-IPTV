#!/usr/bin/env python3
"""Build playlist.m3u — JIO (ztv.json) + Hotstar (hstar.json) + Zee, the sportlink-update way.

Sources follow https://github.com/sportlive18/sportlink-update:
  - JIO:     channels from sportlink-jtv.pages.dev/ztv.json, __hdnea__ cookie from
             Sportlink-wtf/cookie.json, per-channel sports URLs from sportcookie.json
             (jtvplus7.py style: KODIPROP adaptive + clearkey + stream_headers)
  - Hotstar: channels from sportlink-jtv.pages.dev/hstar.json with an hdntl cookie
             (star3.py style), cookie kept fresh from the published tstar.m3u
  - Zee:     merged from the live vk-playlist source (merge.py style)
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ------------------------------ CONFIG ------------------------------
JIO_CHANNELS_URL = "https://sportlink-jtv.pages.dev/ztv.json"
HSTAR_CHANNELS_URL = "https://sportlink-jtv.pages.dev/hstar.json"
COOKIE_URL = "https://raw.githubusercontent.com/sportlive18/Sportlink-wtf/refs/heads/main/cookie.json"
SPORTS_COOKIE_URL = "https://raw.githubusercontent.com/sportlive18/Sportlink-wtf/refs/heads/main/sportcookie.json"
ZEE_SOURCE = "https://vk-playlist.pages.dev/zee3.m3u"
# Fresh hdntl is extracted from this (updated every ~10 min); fallback below if unreachable
HSTAR_COOKIE_SOURCE = "https://raw.githubusercontent.com/sportlive18/sportlink-update/main/tstar.m3u"
HSTAR_COOKIE_FALLBACK = (
    "hdntl=exp=1792648778~acl=%2f*~id=8f07035ffcdefb46e889e5f4db2b0673~data=hdntl"
    "~hmac=c9eb4ea930abbc0ab112596d419c8bf65f681a423b4a21a9df9a17a196de72f1"
)

JIO_USER_AGENT = "Virat"
JIO_REFERER = "https://www.jiotv.com/"
JIO_ORIGIN = "https://www.jiotv.com/"

HSTAR_USER_AGENT = "Virat"
HSTAR_REFERER = "https://www.hotstar.com/"
HSTAR_ORIGIN = "https://www.hotstar.com"

JIO_GROUP_PREFIX = "JioTV"
HSTAR_GROUP_PREFIX = "Hotstar"

OUT = Path("playlist.m3u")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
TIMEOUT = 30

# Hotstar sort order (star3.py): first match wins
HSTAR_PRIORITY = [
    ["bigboss", "big boss", "bigg boss"],
    ["tata ipl"],
    ["savdhaan india"],
]
# ---------------------------------------------------------------------


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def get_json(url: str):
    """Fetch JSON with cache-busting, like jtvplus7.get_json."""
    buster = f"{'&' if '?' in url else '?'}t={int(datetime.now().timestamp() * 1000)}"
    return json.loads(fetch(url + buster))


def split_url_query(url: str):
    p = urllib.parse.urlparse(url)
    base = urllib.parse.urlunparse((p.scheme, p.netloc, p.path, p.params, "", ""))
    return base, (p.query or None)


# ------------------------------ JIO (jtvplus7.py) ------------------------------
def get_jio_cookie() -> str:
    try:
        data = get_json(COOKIE_URL)
    except Exception as e:
        print(f"   WARNING: could not fetch JIO cookie: {e}")
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "cookie" in item:
                return item["cookie"]
        return ""
    if isinstance(data, dict):
        return data.get("cookie", "")
    return ""


def get_sports_urls() -> dict:
    """Per-channel final URLs from sportcookie.json (output/ -> WDVLive/)."""
    try:
        data = get_json(SPORTS_COOKIE_URL)
    except Exception as e:
        print(f"   WARNING: could not fetch sports cookies: {e}")
        return {}
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        results = data.get("successful_results", []) + data.get("failed_results", [])
    else:
        results = {}
    out = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        channel_id = item.get("channel_id")
        final_url = item.get("final_url") or item.get("error_details", {}).get("final_url", "")
        if channel_id and final_url:
            out[str(channel_id)] = final_url.replace("/output/", "/WDVLive/")
    return out


def collect_clearkey_entries(channel: dict) -> list:
    """Ordered (keyId, key) pairs: top-level, keys[], clearkey{} — duplicates kept."""
    entries = []
    if channel.get("keyId") and channel.get("key"):
        entries.append((str(channel["keyId"]), str(channel["key"])))
    keys_arr = channel.get("keys")
    if isinstance(keys_arr, list):
        for k in keys_arr:
            if isinstance(k, dict) and k.get("keyId") and k.get("key"):
                entries.append((str(k["keyId"]), str(k["key"])))
    ck = channel.get("clearkey")
    if isinstance(ck, dict):
        for kid, key in ck.items():
            entries.append((str(kid), str(key)))
    return entries


def jio_entry(channel: dict, cookie: str, sports_urls: dict) -> str:
    name = channel.get("name", "")
    logo = channel.get("logo", "")
    url = channel.get("url", "")
    channel_id = str(channel.get("id", ""))
    group = f"{JIO_GROUP_PREFIX} {channel.get('group') or channel.get('category') or 'Other'}"

    lines = [
        f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{name}" '
        f'tvg-logo="{logo}" group-title="{group}",{name}'
    ]

    is_mpd = (channel.get("type") == "dash") or (".mpd" in url.lower())
    if is_mpd:
        lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")
        ck = collect_clearkey_entries(channel)
        if ck:
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            pairs = ",".join(f"{kid}:{key}" for kid, key in ck)
            lines.append(f"#KODIPROP:inputstream.adaptive.license_key={pairs}")
        elif channel.get("license_url"):
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            lines.append(f"#KODIPROP:inputstream.adaptive.license_key={channel['license_url']}")

    # Final URL: sports channels use their dedicated URL, others get the __hdnea__ cookie
    final_url = sports_urls.get(channel_id) or (
        f"{url}{'&' if '?' in url else '?'}{cookie}" if cookie else url
    )
    base_url, cookie_query = split_url_query(final_url)

    if cookie_query:
        lines.append(
            "#KODIPROP:inputstream.adaptive.stream_headers="
            f"User-Agent={JIO_USER_AGENT}&Referer={JIO_REFERER}&Origin={JIO_ORIGIN}"
            f"&Cookie={cookie_query}"
        )
    lines.append(f"#EXTVLCOPT:http-user-agent={JIO_USER_AGENT}")
    lines.append(f"#EXTVLCOPT:http-referrer={JIO_REFERER}")
    if cookie_query:
        lines.append(f"#EXTVLCOPT:http-cookie={cookie_query}")
    if cookie_query:
        lines.append(f"#EXTHTTP:{json.dumps({'User-Agent': JIO_USER_AGENT, 'Referer': JIO_REFERER, 'Origin': JIO_ORIGIN, 'Cookie': cookie_query})}")
    lines.append(base_url)
    return "\n".join(lines)


# ------------------------------ Hotstar (star3.py) ------------------------------
def get_hdntl_cookie() -> str:
    """Prefer a fresh hdntl from the published tstar.m3u, else the fallback."""
    try:
        text = fetch(HSTAR_COOKIE_SOURCE)
        m = re.search(r"hdntl=[^\s\"&]+", text)
        if m:
            print(f"   -> fresh hdntl from tstar.m3u ({m.group(0)[:50]}...)")
            return m.group(0)
    except Exception as e:
        print(f"   WARNING: could not fetch tstar.m3u for hdntl: {e}")
    print("   -> using fallback hdntl cookie")
    return HSTAR_COOKIE_FALLBACK


def is_mpd(url: str) -> bool:
    try:
        path = urllib.parse.urlparse(url).path
    except Exception:
        path = url
    return path.lower().endswith(".mpd")


def hstar_priority_sort(items: list) -> list:
    buckets = [[] for _ in HSTAR_PRIORITY]
    rest = []
    for it in items:
        name = (it.get("name") or "").lower()
        for i, keys in enumerate(HSTAR_PRIORITY):
            if any(k in name for k in keys):
                buckets[i].append(it)
                break
        else:
            rest.append(it)
    ordered = []
    for b in buckets:
        ordered.extend(b)
    ordered.extend(rest)
    return ordered


def hstar_entry(item: dict, cookie: str) -> str:
    url = (item.get("url") or item.get("mpd_url") or "").strip()
    name = item.get("name", "Unknown")
    logo = item.get("logo", "")
    group = f"{HSTAR_GROUP_PREFIX} {item.get('group') or item.get('category') or 'Other'}"

    lines = [
        f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" '
        f'group-title="{group}", {name}'
    ]

    if is_mpd(url):
        ck = collect_clearkey_entries(item)
        key_id, key = (ck[0] if ck else ("", ""))
        lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")
        lines.append(
            "#KODIPROP:inputstream.adaptive.stream_headers="
            f"User-Agent={HSTAR_USER_AGENT}&Referer={HSTAR_REFERER}"
            f"&Origin={HSTAR_ORIGIN}&Cookie={cookie}"
        )
        lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_id or ''}:{key or ''}")
        if key_id and key:
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")

    lines.append(f"#EXTVLCOPT:http-user-agent={HSTAR_USER_AGENT}")
    lines.append(f"#EXTVLCOPT:http-referrer={HSTAR_REFERER}")
    lines.append(f"#EXTVLCOPT:http-extra-headers=Origin: {HSTAR_ORIGIN}")
    lines.append(f"#EXTVLCOPT:http-cookie={cookie}")
    lines.append(
        f'#EXTHTTP:{{"Origin":"{HSTAR_ORIGIN}","Referer":"{HSTAR_REFERER}",'
        f'"User-Agent":"{HSTAR_USER_AGENT}","Cookie":"{cookie}"}}'
    )
    lines.append(url)  # plain URL, cookie lives in headers only
    return "\n".join(lines)


# ------------------------------ Main ------------------------------
def main() -> None:
    sections = []

    print("1) Build JIO section (ztv.json + cookie.json + sportcookie.json)")
    try:
        channels = get_json(JIO_CHANNELS_URL)
        cookie = get_jio_cookie()
        sports_urls = get_sports_urls()
        print(f"   -> {len(channels)} channels, {len(sports_urls)} sports-specific URLs")
        if cookie:
            print(f"   -> cookie: {cookie[:60]}...")
        else:
            print("   -> no cookie; URLs written bare")
        jio_entries = [jio_entry(ch, cookie, sports_urls) for ch in channels]
        sections.append("\n\n".join(jio_entries))
        print(f"   -> {len(jio_entries)} JIO channels written")
    except Exception as e:
        print(f"   ERROR: JIO section failed: {e}")

    print("2) Build Hotstar section (hstar.json + hdntl)")
    try:
        items = get_json(HSTAR_CHANNELS_URL)
        if isinstance(items, dict):
            items = items.get("items") or items.get("channels") or []
        hdntl = get_hdntl_cookie()
        print(f"   -> {len(items)} channels")
        hstar_entries = [hstar_entry(it, hdntl) for it in hstar_priority_sort(items)]
        sections.append("\n\n".join(hstar_entries))
        print(f"   -> {len(hstar_entries)} Hotstar channels written")
    except Exception as e:
        print(f"   ERROR: Hotstar section failed: {e}")

    print("3) Append Zee section")
    try:
        zee = fetch(ZEE_SOURCE)
        zee_lines = [l for l in zee.splitlines()
                     if l.strip() and not l.startswith("#EXTM3U")]
        print(f"   -> {sum(1 for l in zee_lines if l.startswith('#EXTINF'))} Zee channels")
        sections.append("\n".join(zee_lines))
    except Exception as e:
        print(f"   WARNING: Zee fetch failed, skipping: {e}")

    print("4) Write output")
    content = "#EXTM3U\n\n" + "\n\n".join(s for s in sections if s) + "\n"
    OUT.write_text(content, encoding="utf-8")
    n = content.count("#EXTINF")
    print(f"   -> wrote {OUT} ({OUT.stat().st_size} bytes, {n} channels)")


if __name__ == "__main__":
    main()
