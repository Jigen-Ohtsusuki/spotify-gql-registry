import re
import json
import base64
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

def decode_secret(obfuscated: str) -> str:
    xored = [ord(c) ^ (i % 33 + 9) for i, c in enumerate(obfuscated)]
    joined = "".join(str(n) for n in xored)
    raw_bytes = bytes.fromhex(joined.encode("utf-8").hex())
    return base64.b32encode(raw_bytes).decode().rstrip("=")

def extract() -> list:
    page = requests.get("https://open.spotify.com", headers=HEADERS)
    page.raise_for_status()

    js_urls = re.findall(
        r'https://open\.spotifycdn\.com/cdn/build/web-player/[^"]+\.js',
        page.text
    )
    if not js_urls:
        raise RuntimeError("No JS files found on Spotify web player page")

    for url in js_urls:
        js = requests.get(url, headers=HEADERS).text

        totp_idx = js.find("totpVer:String(")
        if totp_idx == -1:
            continue

        ver_match = re.search(r'totpVer:String\((\w+)\.version\)', js[totp_idx:totp_idx + 100])
        if not ver_match:
            continue

        var_name = ver_match.group(1)
        search_region = js[max(0, totp_idx - 50000):totp_idx]

        array_match = re.search(
            re.escape(var_name) + r"\s*=\s*\[(\{secret\s*:[\s\S]*?)\]\.map",
            search_region
        )
        if not array_match:
            continue

        entries = re.findall(r"\{secret\s*:'(.*?)'.*?version\s*:\s*(\d+)\}", array_match.group(1))
        if not entries:
            entries = re.findall(r'\{secret\s*:"(.*?)".*?version\s*:\s*(\d+)\}', array_match.group(1))
        if not entries:
            continue

        return sorted(
            [{"s": decode_secret(secret), "v": int(version)} for secret, version in entries],
            key=lambda x: x["v"],
            reverse=True
        )

    raise RuntimeError("Could not find TOTP secret in any JS file")

if __name__ == "__main__":
    results = extract()
    print(json.dumps(results, indent=2))
    with open("spotify_totp.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} version(s) to spotify_totp.json (latest: v{results[0]['v']})")