import asyncio
import aiohttp
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SPOTIFY_HOME = "https://open.spotify.com"
CDN_BASE     = "https://open.spotifycdn.com/cdn/build/web-player/"
USER_AGENT   = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HASHES_JSON  = Path("hashes.json")

TARGET_OPS = {"canvas", "fetchPlaylistMetadata",
    "profileAttributes", "libraryV3", "fetchPlaylist",
    "fetchLibraryTracks", "searchTracks", "getAlbum",
    "queryWhatsNewFeed", "home"
}

def _make_pattern(op: str) -> re.Pattern:
    return re.compile(
        rf'"{re.escape(op)}"'
        rf'\s*,\s*"(query|mutation)"'
        rf'\s*,\s*"([a-f0-9]{{64}})"'
    )

_PATTERNS: dict[str, re.Pattern] = {op: _make_pattern(op) for op in TARGET_OPS}


def scan_js(js: str, ops: set[str]) -> dict[str, tuple[str, str]]:
    """Return {op: (hash, type)} for every op found in js."""
    found = {}
    for op in ops:
        m = _PATTERNS[op].search(js)
        if m:
            found[op] = (m.group(2), m.group(1))
    return found


async def fetch(session: aiohttp.ClientSession, url: str, timeout: int = 20) -> str | None:
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if r.status == 200:
                return await r.text()
    except Exception:
        pass
    return None


async def scan_chunk(
    session: aiohttp.ClientSession,
    chunk_name: str,
    chunk_hash: str,
    missing: frozenset[str],
) -> dict[str, tuple[str, str]]:
    """Fetch one webpack chunk and return any ops it contains."""
    js = await fetch(session, f"{CDN_BASE}{chunk_name}.{chunk_hash}.js")
    if not js:
        return {}
    found = scan_js(js, missing)
    for op in found:
        print(f"    [chunk {chunk_name}] ✓ {op}")
    return found


def find_bundle_url(html: str) -> str | None:
    m = re.search(
        r'(https://open\.spotifycdn\.com/cdn/build/web-player/web-player\.[a-f0-9]+\.js)',
        html,
    )
    return m.group(1) if m else None


def extract_chunk_map(js: str) -> list[tuple[str, str]]:
    js_hash_m = re.search(r'\)\+"\."\+\(\{([\d:"a-f,\s]+)\}', js)
    if not js_hash_m:
        candidates = re.findall(
            r'\{(\d+:"[a-f0-9]{8}"(?:,\d+:"[a-f0-9]{8}")*)\}', js
        )
        if not candidates:
            return []
        return re.findall(r'(\d+):"([a-f0-9]{8})"', max(candidates, key=len))

    js_hash_map: dict[str, str] = dict(
        re.findall(r'(\d+):"([a-f0-9]{8})"', js_hash_m.group(1))
    )

    name_m = re.search(
        r'\(\{((?:\d+:"[a-zA-Z][^"]{2,60}"(?:,)?)+)\}\)\[e\]\|\|e\)', js
    )
    name_map: dict[str, str] = {}
    if name_m:
        name_map = dict(re.findall(r'(\d+):"([^"]+)"', name_m.group(1)))
    result: list[tuple[str, str]] = []
    for cid, js_hash in js_hash_map.items():
        name = name_map.get(cid, cid)
        result.append((name, js_hash))

    return result

def load_json() -> dict:
    if HASHES_JSON.exists():
        return json.loads(HASHES_JSON.read_text("utf-8"))
    return {
        "schema_version": 1,
        "operations": {op: {"hash": None, "type": None, "status": "unknown"} for op in TARGET_OPS},
    }


def apply_diff(
    current: dict,
    found: dict[str, tuple[str, str]],
    bundle_id: str,
) -> tuple[dict, bool]:
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ops     = current.setdefault("operations", {})
    changed = False

    for op in TARGET_OPS:
        ops.setdefault(op, {"hash": None, "type": None, "status": "unknown"})

    for op, entry in ops.items():
        if op not in TARGET_OPS:
            continue

        if op in found:
            new_hash, new_type = found[op]
            old_hash = entry.get("hash")

            entry["last_verified"] = now
            entry["type"]          = new_type

            if new_hash != old_hash:
                print(f"  ROTATED  {op}")
                print(f"    old: {old_hash}")
                print(f"    new: {new_hash}")
                if old_hash:
                    entry["previous_hash"] = old_hash
                entry["hash"]         = new_hash
                entry["status"]       = "verified"
                entry["last_changed"] = now
                changed = True
            else:
                if entry.get("status") != "verified":
                    entry["status"] = "verified"
                    changed = True
        else:
            if entry.get("status") != "not_in_bundle":
                print(f"  MISSING  {op} — not found anywhere in bundle")
                entry["status"]        = "not_in_bundle"
                entry["last_verified"] = now
                changed = True

    current["last_updated"] = now
    current["bundle_id"]    = bundle_id
    current["operations"]   = dict(sorted(ops.items()))
    return current, changed

async def main() -> int:
    print("=== Spotify GQL Hash Scraper ===\n")

    async with aiohttp.ClientSession() as session:

        print("1. Fetching Spotify home page...")
        html = await fetch(session, SPOTIFY_HOME)
        if not html:
            print("   ERROR: failed to fetch home page")
            return 1

        bundle_url = find_bundle_url(html)
        if not bundle_url:
            print("   ERROR: bundle URL not found in HTML")
            return 1

        bundle_id = bundle_url.rsplit("/", 1)[-1]
        print(f"   Bundle: {bundle_id}")

        print("2. Fetching main bundle...")
        main_js = await fetch(session, bundle_url, timeout=30)
        if not main_js:
            print("   ERROR: failed to download main bundle")
            return 1
        print(f"   Size: {len(main_js):,} bytes")

        print("3. Scanning main bundle...")
        found: dict[str, tuple[str, str]] = scan_js(main_js, TARGET_OPS)
        print(f"   Found {len(found)}/{len(TARGET_OPS)} ops")

        missing = TARGET_OPS - found.keys()

        if missing:
            print(f"4. Scanning webpack chunks for {len(missing)} missing ops...")
            chunk_map = extract_chunk_map(main_js)
            if not chunk_map:
                print("   WARNING: no webpack chunk map found")
            else:
                print(f"   Firing {len(chunk_map)} chunk requests concurrently...")
                snapshot = frozenset(missing)
                results  = await asyncio.gather(
                    *[scan_chunk(session, chunk_name, chash, snapshot) for chunk_name, chash in chunk_map]
                )
                for batch in results:
                    for op, val in batch.items():
                        if op not in found:
                            found[op] = val
        else:
            print("4. All ops found in main bundle — skipping chunk scan")

        still_missing = TARGET_OPS - found.keys()
        if still_missing:
            print(f"\n   WARNING: could not locate hashes for: {still_missing}")

    print("\n5. Comparing against stored hashes...")
    current          = load_json()
    updated, changed = apply_diff(current, found, bundle_id)

    HASHES_JSON.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if changed:
        print(f"\n✓ hashes.json updated ({len(found)} ops mapped)")
        return 2
    else:
        print(f"\n✓ No hash changes. Timestamps refreshed. ({len(found)} ops verified)")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))