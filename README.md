# spotify-gql-registry

> Automated scraper that keeps Spotify's internal GraphQL operation hashes and TOTP secrets up to date — a background helper for [ZiMusic](https://github.com/jigen-ohtsusuki/zimusic).

[![Update Hashes](https://img.shields.io/github/actions/workflow/status/Jigen-Ohtsusuki/spotify-gql-registry/update-hashes.yml?label=scraper&style=flat-square)](../../actions/workflows/update-hashes.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square)](LICENSE)

---

## What it does

Spotify's internal API uses **persisted queries** — each GraphQL operation is identified by a SHA-256 hash baked into the web player JS bundle. These hashes rotate on every Spotify deploy.

This repo runs a GitHub Actions cron job every **4 hours** that:
1. Fetches the latest Spotify web player bundle
2. Extracts hashes for all target GQL operations
3. Extracts the TOTP secret used for internal token auth
4. Commits changes back to `hashes.json` and `spotify_totp.json`

ZiMusic fetches these files at runtime so it never ships with stale hashes.

---

## Output

### `hashes.json`
Tracks these operations: `canvas`, `fetchLibraryTracks`, `fetchPlaylist`, `fetchPlaylistMetadata`, `getAlbum`, `home`, `libraryV3`, `profileAttributes`, `queryWhatsNewFeed`, `searchTracks`

```json
{
  "operations": {
    "fetchPlaylist": {
      "hash": "a65e12...",
      "type": "query",
      "status": "verified",
      "last_verified": "2026-06-29T10:02:38Z"
    }
  },
  "bundle_id": "web-player.70f6f72c.js"
}
```

### `spotify_totp.json`
```json
[
  { "s": "GM3TMMJTGYZT...", "v": 61 }
]
```
`s` = Base32 TOTP secret, `v` = version. Always use the highest `v`.

---

## Running locally

```bash
pip install -r requirements.txt

python scraper.py              # → hashes.json
python extract_spotify_totp.py # → spotify_totp.json
```

---

## Part of ZiMusic

This scraper exists solely to support [ZiMusic](https://github.com/jigen-ohtsusuki/zimusic) — an Android music app with Spotify, JioSaavn, and YouTube Music integration.

---

## Disclaimer

This project is for **personal, educational, and interoperability purposes** only. It does not bypass authentication — a valid Spotify account and `sp_dc` cookie are required for all API calls. The scraped data reflects information already present in the publicly served web player JavaScript. Use responsibly and in accordance with Spotify's Terms of Service.


---

## License

GPL-3.0 © 2026 JigenxOhtsusuki
