# Email Testing Guide (Target Template)

How to test email-sending features so that "the test passes" actually means "the user will get the email and the link will work in production." Mock-based tests catch almost none of the real-world ways email-auth flows break; this guide documents an end-to-end pattern that does.

This is a copy-into-target template. Place it at `_bmad-output/planning-artifacts/email-testing-guide.md` for any project with email-based features (password reset, email verification, magic-link login, transactional notifications, etc.). Both the bmad-architect (generating CI) and the bmad-dev (writing tests) should read it.

## Why this matters

Mock-based tests for email-sending code can verify exactly one thing: "we called `sendEmail()` with the right arguments." That's a narrow assertion that misses every real failure mode the operator has hit:

- **SMTP misconfigured** in deployed env (wrong host, wrong port, missing auth) — mocked tests pass; deployed app silently swallows emails
- **Email subject / From header wrong** — mocked tests pass; users report "I never got the email" because it landed in spam under the wrong sender
- **Body template broken** — mocked tests pass; recipient sees `Hello, {{ user.first_name }},` literally
- **Reset link URL malformed** — mocked tests pass; user clicks a 404
- **Token validation broken at the receiving endpoint** — mocked tests pass; user clicks the link and gets "Invalid token"
- **Multi-step flow timing** — mocked tests pass; the email arrives AFTER the user retries and the test creates a duplicate
- **Bounce / soft-fail behavior wrong** — mocked tests pass; production silently retries forever or gives up too early

The fix isn't more sophisticated mocks. It's running the real SMTP send against a **fake SMTP receiver that captures email instead of delivering it**, then having the test fetch what was captured and verify the full content + flow.

## The architecture: three environments, one app code path

```
┌──────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│ Local dev / CI   │      │ Railway              │      │ Production VPS  │
│ (operator host)  │      │ (integration test)   │      │                 │
│                  │      │                      │      │                 │
│ App ──SMTP──>    │      │ App ──SMTP──>        │      │ App ──SMTP──>   │
│   Mailpit        │      │   Mailpit            │      │   real SMTP     │
│   (docker-       │      │   (Railway service)  │      │   server        │
│    compose)      │      │                      │      │                 │
└──────────────────┘      └──────────────────────┘      └─────────────────┘
```

The app code is identical across all three environments. **No `if env == "production":` branches.** What changes is environment variables pointing at different SMTP destinations:

| Env var               | Local dev / CI            | Railway                    | Production                    |
| --------------------- | ------------------------- | -------------------------- | ----------------------------- |
| `EMAIL_HOST`          | `localhost`               | `mailpit.railway.internal` | `smtp.your-domain.example`    |
| `EMAIL_PORT`          | `1025`                    | `1025`                     | `587` (or `465`)              |
| `EMAIL_USE_TLS`       | `False`                   | `False`                    | `True`                        |
| `EMAIL_HOST_USER`     | (empty)                   | (empty)                    | (real username)               |
| `EMAIL_HOST_PASSWORD` | (empty)                   | (empty)                    | (real password from secrets)  |
| `DEFAULT_FROM_EMAIL`  | `test@yourdomain.example` | `test@yourdomain.example`  | `noreply@your-domain.example` |

This is the most important pattern in the whole guide: **mock-shaped logic stays out of the app code**. The app always uses real SMTP. Tests run against a real-looking receiver. Production runs against a real production SMTP server (typically a self-hosted Postfix instance on the production VPS, but anything speaking SMTP works — the app code doesn't care). The only difference is configuration.

## Why Mailpit

[Mailpit](https://github.com/axllent/mailpit) is the active successor to MailHog. Three properties make it the right tool here:

1. **Single Docker image, no setup.** `axllent/mailpit:latest`, ~30 MB. SMTP listener on port 1025, web UI + REST API on port 8025. No language-specific tooling.
2. **REST API for programmatic inspection.** `GET /api/v1/messages` returns captured emails as JSON. Tests fetch the latest email, parse headers and body, extract verification links, click them. This is the missing piece in mock-based tests.
3. **Web UI for human debugging.** When something breaks in CI or Railway, open the Mailpit URL — captured emails render in a browser exactly as recipients would see them. Vastly better than tailing application logs.

Other tools work too — MailHog (older), smtp4dev (.NET), Inbucket (Go), MailCatcher (Ruby). Pick Mailpit unless you have a reason not to. It has the best UI and the most stable API.

## Local CI setup — `docker-compose.test.yml`

Add to the target repo a docker-compose file used only for testing:

```yaml
# docker-compose.test.yml — test-time infrastructure (Mailpit + test DB)
services:
  mailpit:
    image: axllent/mailpit:latest
    ports:
      - "1025:1025" # SMTP — app sends here
      - "8025:8025" # HTTP API + web UI — tests query here
    healthcheck:
      test:
        [
          "CMD",
          "wget",
          "--spider",
          "-q",
          "http://localhost:8025/api/v1/messages",
        ]
      interval: 2s
      timeout: 5s
      retries: 5

  test-db:
    image: postgres:17
    environment:
      POSTGRES_PASSWORD: test
      POSTGRES_DB: test_app
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
```

In `scripts/ci.sh`, Phase 1b-bis (just after the DB-migration phase):

```bash
echo "=== Phase 1b-bis: Test infrastructure (Mailpit + test DB) ==="
docker compose -f docker-compose.test.yml up -d --wait
trap 'docker compose -f docker-compose.test.yml down' EXIT

# Tests run with these env vars pointing at the local Mailpit + test DB
export EMAIL_HOST=localhost
export EMAIL_PORT=1025
export EMAIL_USE_TLS=False
export DATABASE_URL=postgresql://postgres:test@localhost:5432/test_app
```

The `trap` ensures Mailpit + the test DB shut down even if tests fail. `--wait` blocks until the healthchecks pass — no need to `sleep` for services to start.

## Railway setup — Mailpit as a service

> **Pre-build setup, driven by Claude.** Mailpit on Railway is provisioned by Claude (via the Railway CLI) **before** the factory rebuild kicks off, the same way Postgres is. Mailpit lives in the **same Railway project** as the target app and Postgres so reference variables (`${{ServiceName.VAR}}`) work across services. See [railway-setup-guide.md](../railway-setup-guide.md) for the canonical command sequence and the **single-attempt-then-verify** rule that prevents duplicate-service creation. The summary below documents the resulting configuration; it is not the procedure for setting it up.

For the integration-test (Railway staging) environment:

1. **Mailpit service** deployed from `axllent/mailpit:latest` in the same Railway project as the target app and Postgres
2. **No public exposure** — both the SMTP port (`1025`) and the web UI / API port (`8025`) stay on Railway's private network. The app reaches both via `mailpit.railway.internal`. Mailpit listens on two ports inside the container; adding a public domain without an explicit `targetPort` makes Railway's network auto-config error out and the deployment fails (recovered case: PawprintRecipes 2026-05-06). Private-only avoids that whole class of failure.
3. **App service env vars**:
   ```
   EMAIL_HOST=mailpit.railway.internal
   EMAIL_PORT=1025
   EMAIL_USE_TLS=False
   EMAIL_HOST_USER=
   EMAIL_HOST_PASSWORD=
   DEFAULT_FROM_EMAIL=test@yourdomain.example
   ```
   No `MAILPIT_WEB_URL` — Mailpit's API is reached at `http://mailpit.railway.internal:8025` from inside Railway. Set `MAILPIT_API_URL` only on the **test/E2E** service (which runs inside Railway's network) and never on the production service.
4. **Verification:** confirm mailpit's latest deployment is `SUCCESS` and not stopped (`railway status --json`). Trigger a password-reset / verification flow on the deployed app; the E2E test suite — which runs inside Railway and so has private-network access — fetches captured emails via the API and asserts on From, Subject, body, and link.

When the operator personally needs to browse captured emails (rare; usually only when an E2E test fails and the rendered email needs human inspection), spin up a temporary public domain with an explicit port and **delete it after**:

```bash
railway domain --service mailpit --port 8025      # temporary
# ...browse mailpit-production-XXXX.up.railway.app...
# Delete the domain from the dashboard before walking away.
```

Don't leave the domain in place. Mailpit listening on two ports plus a no-`targetPort` domain is the original failure mode this section exists to prevent.

## End-to-end test pattern (Playwright + Mailpit API)

The pattern that catches real-world bugs:

```typescript
// e2e/auth/password-reset.spec.ts
import { test, expect } from "@playwright/test";

const MAILPIT_API = process.env.MAILPIT_API_URL ?? "http://localhost:8025";

async function getLastEmailFor(
  request,
  recipient: string,
  subjectMatch: RegExp,
) {
  // Mailpit returns messages newest-first
  const resp = await request.get(`${MAILPIT_API}/api/v1/messages`);
  const { messages } = await resp.json();
  const match = messages.find(
    (m) =>
      m.To.some((t) => t.Address === recipient) && subjectMatch.test(m.Subject),
  );
  if (!match)
    throw new Error(
      `No email matching subject ${subjectMatch} for ${recipient}`,
    );
  // Fetch full body
  const full = await request.get(`${MAILPIT_API}/api/v1/message/${match.ID}`);
  return await full.json();
}

test("password reset full flow (story_3_4)", async ({ page, request }) => {
  // STAGE 1 — trigger the reset
  await page.goto("/auth/forgot-password");
  await page.fill('input[name="email"]', "alice@example.com");
  await page.click('button[type="submit"]');
  await expect(page.locator(".success-message")).toBeVisible();

  // STAGE 2 — verify the email arrived AND verify content
  const email = await getLastEmailFor(
    request,
    "alice@example.com",
    /password reset/i,
  );
  expect(email.From.Address).toBe("noreply@yourdomain.example");
  expect(email.Subject).toMatch(/^Password reset/);
  // Confirm the body has the user's name (caught a {{ user.first_name }} template bug once)
  expect(email.Text).toMatch(/Hi Alice/);

  // STAGE 3 — extract the reset link AND verify the URL shape
  const linkMatch = email.Text.match(
    /https?:\/\/[^\s]+\/auth\/reset\?token=[\w-]+/,
  );
  expect(linkMatch, "reset link missing or malformed").toBeTruthy();

  // STAGE 4 — click the link AND verify it resolves to the reset page
  await page.goto(linkMatch[0]);
  await expect(page).toHaveURL(/\/auth\/reset\?token=/);
  await expect(page.locator('input[name="newPassword"]')).toBeVisible();

  // STAGE 5 — set new password AND verify the new credentials work
  await page.fill('input[name="newPassword"]', "newSecure!Pass1");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(/\/dashboard/);
});
```

This is **one test, five stages, ten distinct assertions**. Each stage catches a different class of real-world failure that mock-based tests miss. The extra ~30 lines of test code vs a mocked equivalent is worth it because:

- Stages 2-3 alone would have caught the "wrong From header / template not rendered" bugs that traditionally make it to production
- Stage 4 catches token-malformed-URL bugs that pure backend tests skip entirely
- Stage 5 catches "the new password doesn't actually work" bugs (a separate bug class from "the reset endpoint returned 200")

## Required behaviors

|            |                                                                                                                                                                                                              |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **MUST**   | Every email-touching feature has at least one E2E test that exercises the full flow through Mailpit, asserting on email content (subject, From, body), link extraction, link navigation, and post-link state |
| **MUST**   | Tests reset Mailpit's state between runs — call `DELETE /api/v1/messages` in `beforeEach` (or use ephemeral docker compose containers) to avoid flakiness from prior test emails                             |
| **MUST**   | The app's email-sending code path is **identical** in test and production. No `if settings.TESTING:` branches. The difference is environment variables only                                                  |
| **SHOULD** | Test env vars set `DEFAULT_FROM_EMAIL` to a domain that's clearly fake (`test@yourdomain.example`) so production traffic is impossible if env vars accidentally leak                                         |
| **SHOULD** | Email tests run in the integration-tier of the test pyramid (story-scoped, ~5-30s each), not the unit tier (which stays mock-free of any email handling)                                                     |
| **SHOULD** | When CI fails on an email assertion, the operator can browse the rendered email by adding a *temporary* public domain to the Mailpit service (`railway domain --service mailpit --port 8025`) and deleting it after. Mailpit stays private by default — see "Railway setup" above for why                            |

## Anti-patterns

| Anti-pattern                                                                          | Why it hurts                                                                                             | Fix                                                                                                                                                     |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mocking `sendEmail()` at the function level instead of substituting the SMTP receiver | The real SMTP send code path never runs; misconfiguration ships to prod                                  | Configure `EMAIL_HOST` to point at Mailpit; let the framework's real SMTP code run                                                                      |
| Asserting only that `sendEmail()` was called                                          | Misses everything that happens AFTER the call (template rendering, header construction, link generation) | Assert on the captured email's actual headers + body via Mailpit API                                                                                    |
| Test extracts link via hard-coded URL pattern                                         | When base URL changes (e.g. https vs http, port differences), tests break in mysterious ways             | Extract via regex that captures the full URL; pass through `page.goto()` so any malformed URL fails fast                                                |
| Shared Mailpit instance across parallel test runs without inbox isolation             | Test A's email leaks into Test B's assertion; flakiness                                                  | Each test calls `DELETE /api/v1/messages` in setup, or use unique recipient addresses (`alice+story_3_4@example.com`)                                   |
| Skipping the "click the link in the email" step                                       | The endpoint receiving the link is untested in the integration tier                                      | Always click the link in tests; never assume the URL is valid just because the regex matched                                                            |
| `if env == "test": skip_email_sending = True` in app code                             | The skip path bypasses the bug-prone real send code; production hits the bug                             | Never branch app code on environment for email sending. Use env vars + Mailpit instead                                                                  |
| Production env vars accidentally pointing at Mailpit                                  | Real users get no emails, silently                                                                       | Use a `DEFAULT_FROM_EMAIL` of `*.example` in test/Railway and a real domain in production; alert if any email FROM `*.example` lands in production logs |

## Multi-component considerations

For projects spanning a backend and a frontend (e.g. Django + Next.js):

- The **backend** sends the emails (Django's `send_mail()` or equivalent). It needs `EMAIL_HOST`, `EMAIL_PORT`, etc. configured at deploy time
- The **frontend** doesn't talk to SMTP at all — it just triggers backend endpoints that send the email. So no email env vars on the frontend service
- E2E tests live in the **monorepo root** under `e2e/`, not inside backend/ or frontend/. They drive the frontend (via Playwright) and assert against Mailpit's API
- Mailpit's API URL is a **test-only env var** (`MAILPIT_API_URL=http://localhost:8025` in local dev, `http://mailpit.railway.internal:8025` for E2E tests running inside Railway, never set in production). Tests cannot hit Mailpit from outside Railway because Mailpit is private-only by design — run E2E suites from a Railway service or run them locally against the docker-compose Mailpit instead

## How the bmad-architect agent should use this guide

When generating `scripts/ci.sh` for a project that lists email features in `epics.md` or `prd.md`, the architect MUST:

1. Add `docker-compose.test.yml` to the target with a Mailpit + test-DB stanza
2. Add a "Phase 1b-bis: test infrastructure" block to ci.sh that starts/stops the compose file
3. Generate test scaffolding (`e2e/auth/`, `tests/factories/email.ts` if applicable) consistent with this guide's E2E pattern
4. Document the env-var separation in the target's `README.md` so future operators know production needs different SMTP config

The architect SHOULD also note in `approved-tech-stack.md` that Mailpit is the test-time email service, with a one-line link to this guide.

## How the bmad-dev agent should use this guide

When implementing any story whose acceptance criteria mention email sending, the dev agent MUST write at least one test conforming to the E2E pattern above (the five-stage Playwright + Mailpit-API flow). Mock-based unit tests for email handling are acceptable as a complement (verifying business logic around when to send) but cannot be the only assertion — every email feature gets one E2E test.

## How the operator validates email setup

Before kickoff:

1. Confirm `docker-compose.test.yml` exists and includes Mailpit
2. Run `docker compose -f docker-compose.test.yml up -d --wait`; open `http://localhost:8025` and verify the empty Mailpit inbox
3. Trigger a manual test send: `swaks --to test@example.com --server localhost:1025` (or equivalent)
4. Confirm the email appears in the Mailpit inbox

After deploying to Railway:

1. Confirm Mailpit's latest deployment is `SUCCESS` and not stopped: `railway status --json` → mailpit.latestDeployment.status. (Mailpit's web UI is private — no public URL to open.)
2. Hit a deployed endpoint that sends an email (manual login → password reset)
3. Confirm the email arrived by running the E2E test suite from inside Railway, or — for one-off manual inspection — temporarily add a public domain (`railway domain --service mailpit --port 8025`), browse the captured email, then delete the domain

After cutover to VPS production:

1. Confirm `EMAIL_HOST` env var is the real production SMTP server (e.g., the local Postfix instance on the VPS at `localhost:25`, or a remote SMTP host), NOT Mailpit
2. Confirm `DEFAULT_FROM_EMAIL` is your real production sender, NOT `*.example`
3. Log a `production_email_sent` event on every send and audit it against expected sender domains

## Updating this guide

Update when a real-world email-related production incident reveals a failure mode this guide didn't anticipate. Add the failure to the anti-patterns table with the receipt. Don't add hypothetical anti-patterns — only real-world ones with traceable history.

## See also

- [local-dev-docker-guide.md](local-dev-docker-guide.md) — the local-dev side: Mailpit lives in the same `docker-compose.yml` as the app and Postgres; this guide is the test-side
- [test-structure-guide.md](test-structure-guide.md) — broader test pyramid; email tests live in the integration tier
- [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md) — story ACs for email features should specify the full flow (send + receive + click + state-change), not just the send
- [ci-script-specification.md](ci-script-specification.md) — Phase 1b-bis (test infrastructure startup) sits alongside the existing Phase 1b (DB schema sync)
- [../railway-setup-guide.md](../railway-setup-guide.md) — Railway side of the Option B topology (staging UAT environment)
- [Mailpit documentation](https://mailpit.axllent.org/) — full REST API reference, configuration options
