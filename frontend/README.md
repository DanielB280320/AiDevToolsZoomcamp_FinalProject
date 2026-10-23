# FitWise frontend

React + TypeScript SPA built with Vite (spec §7.1). Requires Node.js 24 (`.nvmrc`;
`engine-strict` in `.npmrc` makes `npm ci` fail on older versions). From the repository root,
`make up` serves the built SPA through nginx (`frontend/Dockerfile`, `nginx/default.conf.template`,
which proxies `/api` to the backend and falls back to `index.html` for client routes) and
`make lint` / `make test` wrap the commands below.

```bash
npm ci
npm run dev           # http://localhost:5173, proxies /api to API_PROXY_TARGET (default http://localhost:8000)
npm test              # Vitest + React Testing Library (tests/ only; API mocked with MSW from openapi.yaml shapes)
npm run lint          # eslint, including i18next/no-literal-string
npx tsc --noEmit      # type-check
npm run build         # static bundle in dist/
npm run generate:api  # regenerate src/api/schema.d.ts from ../openapi.yaml
npm run check:api     # fails if src/api/schema.d.ts is out of date (CI)
```

## Conventions

- **API client**: `src/api/client.ts` wraps `openapi-fetch` with the generated `src/api/schema.d.ts`
  (base URL `/api/v1`, cookie credentials). Never hand-write request or response types; change
  `openapi.yaml`, run `npm run generate:api` and commit both (ADR 0005).
- **Errors**: map `application/problem+json` responses with `toProblemDetails` / `problemFromResponse`
  from `src/api/problem.ts` to `{code, detail, fieldErrors}`.
- **Strings**: every UI string lives in `src/i18n/en.json` and is read with `useTranslation()`.
  Lint fails on literal JSX text and user-facing attributes (spec §6.2).
- **Layout**: mobile-first; check 360 px and 1280 px (spec §6.1). Every route renders inside
  `AppShell` (header, content, footer with the §6.3 disclaimer).
- **Session**: `src/api/session.ts` holds the signed-in user (`GET /me`, query key `["me"]`).
  Signed-in pages sit under `RequireAuth` (a 401 redirects to `/sign-in`) and read the user with
  `useSignedInUser()`. API failures are `ApiError`s (`src/api/errors.ts`, with `Retry-After`);
  forms map them with `problemToFormErrors` (`src/auth/forms.ts`).
- **Tests** live in `tests/`. Requests without an MSW handler fail the test; no real network.
  `renderApp(path)` renders the real routes and returns the router for location assertions;
  `tests/mocks/fixtures.ts` builds `Me` and problem responses.
