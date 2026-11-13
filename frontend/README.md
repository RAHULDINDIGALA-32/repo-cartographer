# repo-cartographer frontend

The F1 frontend is a client-rendered Next.js App Router application. It calls
the FastAPI backend directly, including the POST/SSE ask stream; it never puts
backend credentials in the browser and never proxies ask requests through
Next.js.

## Setup

Use Node 20 or newer. Keep `node_modules` and `.next` outside OneDrive when
possible.

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the backend origin (`http://localhost:8000`
locally, or the Render URL in Vercel). Only this public URL and the optional
brand name belong in `NEXT_PUBLIC_*`; admin keys must never be placed here.

## Scripts

`npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`, and
`npm run format:check` are the release checks. `npm run gen:api` regenerates
types from the committed `../docs/openapi.json` snapshot; it never fetches a
deployed server. SSE payloads remain runtime-validated with Zod because SSE is
not represented in the OpenAPI snapshot.

## Structure and design

`src/api` contains the typed fetch/SSE client, `src/hooks` owns backend/repo/
ask state, and `src/components` contains the shell and turn UI. Design tokens
and accessibility rules are documented in [design-tokens.md](design-tokens.md).
The app uses pure white/black page backgrounds, neutral text, pastel fills and
borders, keyboard-visible focus, reduced-motion support, and no per-token
animation.

## Deployment

In Vercel, set Root Directory to `frontend`, use the Next.js preset, and set
`NEXT_PUBLIC_API_BASE_URL` for both production and the selected preview
environment. Add the local and production frontend origins to the backend
`CORS_ORIGINS`, then deploy the backend before testing the frontend.

## Known limitations

The source viewer, retrieval inspector, history, sharing, admin views, and
feedback controls are intentionally deferred to later frontend phases. The
first F1 build should be run outside OneDrive for reliable dependency caching.
