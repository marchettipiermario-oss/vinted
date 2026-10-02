# Vinted Bot — PRD

## Original Problem Statement
"ciao voglio che mi costruisci un bot per vinted che mi faccia vedere in tempo reale i risultati secondo determinati criteri di ricerca che gli dico, e che mi permetta di fare autobuy"

## Target Persona
A Vinted power-user/reseller who wants to monitor new listings matching saved criteria and snipe-buy items the moment they appear, before other buyers.

## Tech Stack
- Backend: FastAPI + MongoDB (motor), bcrypt + PyJWT auth (httpOnly cookie + Bearer fallback)
- Vinted client: `requests` Session targeting `/api/v2/catalog/items` + `/api/v2/transactions`
- Frontend: React 19 + React Router + Sonner toasts, neo-brutalist design (Archivo + JetBrains Mono)

## Implemented (v1 — 2026-02)
- JWT auth: register/login/logout/me (admin seed `admin@vintedbot.local / admin123`)
- Vinted session config (domain + cookie + UA) per user
- Saved Searches CRUD with autobuy + max_autobuy_price
- Live monitoring page: 10s polling, diff vs previously seen items, "NEW" badge
- Manual buy button (per item) + automatic buy when armed
- Stats dashboard: total searches, items today, autobuys total/ok
- Autobuy log
- Neo-brutalist design with hard borders, JetBrains Mono accents

## Known Limitations
- Real autobuy requires a valid logged-in Vinted session cookie pasted in Settings; without it, only public searches work.
- Vinted may rate-limit / require residential proxies for heavy use; raw HTTP is fragile but functional for low-frequency polling.
- 10s polling only runs while the user has the search detail page open (no server-side background worker yet).

## Backlog (P1)
- Background worker (APScheduler) so monitoring runs even when UI is closed
- Telegram / Email notifications
- Multi-account Vinted sessions
- Per-search proxy support
- Brand/Size/Catalog autocomplete (fetch Vinted ref data)

## Backlog (P2)
- Statistics charts (Recharts)
- Price-drop detection
- Shareable search templates

## Crosslist (v2 — 2026-10)
Request: "puoi creare un software che pubblica su vinted, subito, marketplace e ebay?"
- Page `/listings` (nav "Crosslist"): one listing (photos, title, price, brand, size, condition, per-platform price + categories) published to several platforms.
- eBay: automatic via official Sell Inventory API (`inventory_item` → `offer` → `publish`, withdraw on sale). Config in Settings → eBay (App ID/Cert ID, refresh token, business policies, location). Requires `PUBLIC_BASE_URL` env so eBay can fetch photos from `/api/crosslist/photos/...`.
- Vinted: automatic via unofficial web API (`/api/v2/photos`, `/api/v2/item_upload/items`) with the primary session cookie. Experimental; needs `vinted_catalog_id`.
- Subito + Facebook Marketplace: no public API → assisted mode (platform-formatted copy, photo download, link to the post form, then "mark published").
- "Venduto su…" marks sold and removes the listing elsewhere (eBay withdraw, Vinted delete; Subito/Marketplace flagged "RIMUOVI!").
- Code: `backend/crosslist.py`, tests in `tests/test_crosslist.py`. Photos stored in `UPLOAD_DIR` (default `backend/uploads/`).

## PC agent for Subito + Marketplace (v3 — 2026-10)
Request: "trova il modo per non farlo assistito, tipo comandando tu il computer"
- `agent/` is a local Playwright agent the user runs on their own PC with a dedicated, logged-in Chrome profile.
- Backend queue: `POST /crosslist/agent/token` (hash stored), agent calls `POST /crosslist/agent/jobs/claim` and `/agent/jobs/{id}/result` with `X-Agent-Token`. Publishing Subito/Facebook queues a job when an agent token exists (else assisted mode); "Venduto su…" queues delete jobs. Stale running jobs are re-claimed after 15 min.
- Flows locate fields by label/placeholder/accessible name (IT + EN), pick free options on upsell pages, stop on payment pages, and hand over to the user with a yellow banner when stuck (login, captcha, unknown field).
- Tested against local stand-in pages (`tests/test_agent_sites.py`); not yet verified against the live Subito/Facebook forms.

## Claude Code mode (v4 — 2026-10)
Request: "fai fare tutto a claude code"
- Skill `.claude/skills/pubblica-annunci/SKILL.md`: Claude Code on the user's PC (with Claude in Chrome or computer use) loops `agent/crosslist_agent.py claim` → publishes/removes in the user's Chrome → `report <id> --ok/--error`. Can be scheduled with `/loop 15m /pubblica-annunci`.
- Same safety rules as the Playwright agent: never pay, free options only, stop on captcha/2FA/login.
