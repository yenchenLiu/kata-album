# Kata Album (Home Assistant custom integration)

On-demand photo and people browser for Kata Friend. Photos stay on the device; nothing is written to disk.

## Install (HACS)
1. HACS -> three-dot menu -> Custom repositories -> add this repo's URL, category **Integration**.
2. Download **Kata Album**, then restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> Kata Album; paste the private export JSON.
4. Add the card to a dashboard: `type: custom:kata-album-card`, `entry_id: <config entry id>`.
   The card JS ships inside the integration and is loaded automatically (no `/config/www` copy, no manual dashboard resource).
   Options: `max_height` (640 px; scroll within the card), `title`, `min_tile` (160 px, responsive grid), `columns` (fixed count; overrides `min_tile`), `page_size` (60), `days_per_load` (7, max 31), `max_days` (365).
   Newest 7 days load first; older windows load as you scroll; empty days are skipped. Click a photo for a lightbox (arrow keys / swipe; shows the 1600x1200 preview, "Original" loads the full PNG). The date picker jumps to a day.
5. Delete any temporary copy of the export JSON from the HA host.
Updates: HACS shows a new release; download it and restart HA. The card URL carries the integration version, so browsers fetch the new card automatically.

Manual install also works: copy `custom_components/kata_album/` to `/config/custom_components/` and restart.

## Export format
Schema 1 (browse only) or schema 2 (adds `initialization.notify` = `{type: mqtt, url: <callback topic>}`).
Without the callback, browsing works but `1021` auto-recovery and the "Reopen local service" button are disabled.

## API
`GET /api/kata_album/<entry_id>/photos?start=YYYY-MM-DD&end=YYYY-MM-DD` (max 31 days, default last 30 (the card asks for 7); `?date=` for one day), newest first, each item carries its local `date`. Images: `.../photos/<id>/thumbnail|preview|original` (5 / 10 / 25 MiB caps). Admin only.

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
`uv run --with aiohttp --with pytest pytest tests` and `node --test tests/frontend.test.cjs`. Python tests cover auth, local protocol and coordinator/API contracts with HA doubles; JavaScript tests cover card logic with browser doubles. Full HA runtime and rendered UI remain untested.


## People and photo deletion (0.5.0)
- **Album / People** switch between separate views; **Collapse / Expand** hides the content. `max_height` controls the scroll area (default 640 px, minimum 200).
- People are grouped as familiar / strangers, with lazy-loaded local avatars. Select a person for a 20-item cursor-based photo review; Back returns to people. Familiar-person statistics are optional: missing `start` is supported.
- The photo lightbox has **Delete**, with explicit permanent-deletion confirmation. Only a single, previously listed photo can be deleted. The backend maps its opaque ID to the original device ID; users cannot submit arbitrary device IDs. After the device acknowledges the delete, the backend re-lists the photo's own second and only reports success if it is gone; otherwise the API returns 502 `delete_unconfirmed`. On an uncertain result, reload and verify before retrying.
- All new endpoints remain admin-only and use `Cache-Control: no-store`:
  - `GET /api/kata_album/<entry_id>/people`
  - `GET /api/kata_album/<entry_id>/people/<id>/avatar`
  - `GET /api/kata_album/<entry_id>/people/<id>/photos?cursor=<Unix seconds>`
  - `GET /api/kata_album/<entry_id>/people/<id>/stats`
  - `DELETE /api/kata_album/<entry_id>/photos`, JSON `{ "id": "<opaque photo ID>", "confirm": true }`
- Live read-only testing confirmed 9225, 9226, 9227 and `faces/.../raw_mini.jpg`. Real deletion has **not** been performed. A full 20-item multi-page dataset and a real HA UI still need acceptance testing. Tests with HA doubles validate contracts; they do not constitute a deployed HA test.
- No video, person rename/merge/delete or face upload is added in this version. The App's hard-coded February 2026 person-date filter is deliberately omitted so the integration lists all returned people.
