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
