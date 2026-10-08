# Kata Album (Home Assistant custom integration)

Read-only, on-demand photo browser for Kata Friend. Photos stay on the device; nothing is written to disk.

## Install (HA OS)
1. Back up HA. 2. Copy `custom_components/kata_album` to `/config/custom_components/`.
3. Copy `www/kata-album-card.js` to `/config/www/`. 4. Restart HA.
5. Settings -> Devices -> Add integration -> Kata Album; paste the private export JSON.
6. Dashboard resources: add `/local/kata-album-card.js` as a JavaScript module.
7. Card: `type: custom:kata-album-card`, `entry_id: <config entry id>`, optional `title`, `columns` (3), `page_size` (50), `days_per_load` (30, max 31), `max_days` (365).
   The card is a date-grouped timeline: newest 30 days first, older windows load as you scroll; empty days are skipped. The date picker jumps to a day.
8. Delete any temporary copy of the export JSON from the HA host.

## Export format
Schema 1 (browse only) or schema 2 (adds `initialization.notify` = `{type: mqtt, url: <callback topic>}`).
Without the callback, browsing works but `1021` auto-recovery and the "Reopen local service" button are disabled.

## API
`GET /api/kata_album/<entry_id>/photos?start=YYYY-MM-DD&end=YYYY-MM-DD` (max 31 days, default last 30; `?date=` for one day), newest first, each item carries its local `date`. Thumbnails/originals: `.../photos/<id>/thumbnail|original`. Admin only.

## Security notes
- Credentials live in the HA config entry (and therefore in HA backups, which HA does not encrypt by itself).
- Album API is admin-only. Image IDs are opaque, per-run salted; the proxy only fetches `/download/...` paths the device itself listed, never follows redirects, enforces content type and size (5 MiB thumb / 25 MiB original), and sends `Cache-Control: no-store`.
- Browsers and the OS may still hold image data in memory/swap.

## Limits
- refreshToken may expire; HA then shows a re-auth prompt (paste a fresh export). Cognito branch `2006` is treated as re-auth.
- `1021` does not fix every crash. Recovery success = heartbeat + album query actually working. `1024` and device reboot are never called.
- The device must be reachable from HA's LAN.

## Verify before release (open items)
- **Confirmed live:** refresh, `9230` (`deviceID`+`propertyIDs`), `1021` (with `notify`, `.../funcResp`), heartbeat, `9217`, and `/download/<path>_thumb.jpg` / `.png`.
- **Not yet verified:** whether `1021` works without `notify` or with the App closed; `cloud.py` now sends the same `terminalID`/`uuid`/`UserID` headers as the App's `1021`.
- **Plan section 7B:** with the App fully closed, call `1021` from this client and confirm shadow + local requests succeed. If it fails, do not advertise app-free recovery.
- **Plan section 7E:** 48 h soak test on a real HA.

## Status values
`healthy`, `empty`, `recovering`, `auth_required`, `error`. A separate `offline` state is not implemented: the `9230` response has no verified online flag, so an unreachable device appears as `error`.

## Tests
`uv run --with aiohttp --with pytest pytest tests` (core auth/local logic; HA glue is untested without a HA environment).
