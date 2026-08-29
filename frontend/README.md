# ExpTrack Frontend

React + Vite + TypeScript SPA for the four ExpTrack UIs: `/review`, `/view`, `/shared`, `/recurring`.

## Development

```bash
npm install
npm run dev
```

`vite.config.ts` proxies `/api`, `/trigger`, `/login`, `/logout`, `/register` to `http://localhost:8080`, so run the Flask app locally alongside the dev server:

```bash
cd ../loader && PORT=8080 python app.py
```

## Build

```bash
npm run build
```

Outputs to `../static/dist` (relative to this directory). In production, `loader/app.py`'s `spa_catch_all` route serves the built assets and falls back to `index.html` for client-side routes; `Dockerfile` builds this automatically as part of the image build.

## Auth

The SPA calls `GET /api/me` on load to determine the signed-in user. It supports both session-cookie auth (via `/login`) and `ADMIN_TOKEN` query-param auth (`?token=...`), matching the Flask backend's `require_admin`/`require_any_auth` decorators. An admin token, once supplied via the URL, is persisted to `sessionStorage` so it survives client-side navigation and page reloads within the same tab.

## Lint

```bash
npm run lint
```
