# Bug: SPA Static File Serving Not Wired (Stories 1.4 & 2.7 Gap)

## Date Identified

2026-03-28

## Summary

The Ship Rebuild Go server embeds the compiled React frontend via `//go:embed static` but never registers an HTTP handler to serve those files. Additionally, the auth middleware blocks all non-API paths (including `/`, `/login`, `/register`) with a 401, preventing the SPA from loading in a browser. This is a gap between Story 1.4 (which set up the embed) and Story 2.7 (which built the React components but assumed they'd be served).

## Symptoms

- Visiting `https://shiprebuild-production.up.railway.app/` returns:
  ```json
  {"error":{"code":"UNAUTHORIZED","message":"Authentication required"}}
  ```
- The response comes from the Go auth middleware (not Railway edge auth)
- Response times are fast (microseconds) because the middleware rejects before any handler runs
- The `/healthz` endpoint works (it's in the auth bypass list)
- The Go server IS running and healthy — this is purely a routing/middleware issue

## Root Cause

### File: `api/cmd/server/main.go`

Search for the `//go:embed static` directive and the TODO comment referencing `story-N`. The embedded filesystem variable `staticFiles` holds the compiled React app (index.html, JS bundles, CSS) but is never used. No `http.FileServer` or handler is registered to serve these files.

```go
//go:embed static
// TODO(story-N): wire staticFiles to http.FileServer once SPA routing is implemented.
var staticFiles embed.FS
```

### File: `api/internal/middleware/auth.go`

Search for the `NewAuth` function and its `switch r.URL.Path` block. Only three paths bypass authentication. The SPA routes (`/`, `/login`, `/register`) and static assets (`/assets/*`) are not in this list, so they all get a 401 before reaching any handler.

```go
switch r.URL.Path {
case "/healthz", "/api/v1/login", "/api/v1/register":
    next.ServeHTTP(w, r)
    return
}
```

## Why This Wasn't Caught

- Story 1.4 created the embed directive and Dockerfile multi-stage build but left a TODO for the file server wiring
- Story 2.7 built all the React components (LoginPage, RegisterPage, AppShell, ProtectedRoute) but focused on frontend code, not Go server wiring
- The E2E tests for Story 2.7 were written with `test.skip()` (RED phase), so they never actually tried to load the app in a browser
- The TODO references `story-N` (a placeholder), but no story was ever created for this work

## Impact

- Users cannot see the login screen or any part of the web UI
- All future frontend E2E tests (Epics 4-9) will fail when they try to load the app in a browser
- The Railway deployment is effectively API-only despite having a complete frontend compiled into the binary

## Fix

See the implementation spec at:
`_bmad-output/implementation-artifacts/bug-1-4-and-2-7-spa-static-serving.md`

Two files need changes (~20 lines total):
1. `api/cmd/server/main.go` — register SPA file server handler
2. `api/internal/middleware/auth.go` — add frontend paths to auth bypass

## Verification

After the fix, these should work:
- `curl https://shiprebuild-production.up.railway.app/` returns HTML (the React SPA index.html)
- `curl https://shiprebuild-production.up.railway.app/healthz` returns `{"status":"ok"}` (unchanged)
- `curl https://shiprebuild-production.up.railway.app/api/v1/me` returns 401 (API auth still enforced)
- Visiting the URL in a browser shows the login page
