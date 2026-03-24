# Story 6.1: Cloud Deployment

Status: ready-for-dev

## Story

As an evaluator,
I want the Shipyard agent and the agent-built Ship app both publicly accessible,
so that I can interact with them live without cloning the repo.

## Acceptance Criteria

1. **Given** the Docker container runs locally **When** deployed to Railway (or equivalent hosting) **Then** the Shipyard agent is accessible via public URL with the `/instruct` endpoint working
2. **Given** the Ship app was rebuilt by the agent **When** it is deployed **Then** the Ship app is publicly accessible at its own URL

## Tasks / Subtasks

- [ ] Task 1: Verify local Docker build is production-ready (AC: #1)
  - [ ] Run `docker build -t shipyard .` and confirm it builds cleanly
  - [ ] Run `docker compose up` and verify the FastAPI server starts on port 8000
  - [ ] Hit `POST /instruct` locally to confirm the endpoint responds
  - [ ] Ensure `.env.example` documents all required environment variables (ANTHROPIC_API_KEY, LANGCHAIN_* vars)
- [ ] Task 2: Configure Railway project for the Shipyard agent (AC: #1)
  - [ ] Create a Railway project (or equivalent PaaS) linked to the repo
  - [ ] Set environment variables: ANTHROPIC_API_KEY, LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT
  - [ ] Configure the service to use the existing `Dockerfile` with port 8000 exposed
  - [ ] Deploy and verify the public URL is assigned
- [ ] Task 3: Validate the deployed Shipyard agent (AC: #1)
  - [ ] Send a `POST /instruct` request to the public URL with a simple task
  - [ ] Confirm the agent processes the request and returns a valid response
  - [ ] Verify LangSmith tracing still works from the deployed instance
  - [ ] Check logs for any startup errors or missing config
- [ ] Task 4: Deploy the agent-built Ship app (AC: #2)
  - [ ] Identify the Ship app's build output from the `{target_dir}/` directory
  - [ ] Create a separate Railway service (or static hosting) for the Ship app
  - [ ] Deploy the Ship app and confirm it is publicly accessible at its own URL
  - [ ] Verify the Ship app loads and is functional
- [ ] Task 5: Document deployment URLs and configuration (AC: #1, #2)
  - [ ] Add deployment URLs to README.md (live agent URL, live Ship app URL)
  - [ ] Document any Railway-specific configuration in the README
  - [ ] Ensure `.env.example` is up to date with all required variables for deployment

## Dev Notes

- **Existing Dockerfile is ready.** The `Dockerfile` at project root already builds a Python 3.13-slim image, installs requirements, copies `src/`, creates a non-root user, exposes port 8000, and runs uvicorn. No modifications should be needed unless deployment reveals issues.
- **docker-compose.yml exists** per the architecture spec. Use it for local validation before deploying.
- **Railway is the preferred platform** per the architecture doc ("Docker + docker-compose for containerization — local for MVP, Railway for Final"). If Railway is unavailable, Render or Fly.io are acceptable alternatives.
- **Two separate deployments are needed.** The Shipyard agent (FastAPI/Python) and the Ship app (likely a frontend app) are independent services with independent URLs.
- **Environment variables are secrets.** Never commit API keys. Railway's environment variable UI or `railway variables` CLI should be used.
- **FR13 compliance:** This story directly satisfies FR13 — "Agent and agent-built Ship app both publicly accessible."

### Dependencies

- **Requires:** Story 1.6 (Persistent Server + CLI Entry Point) — the FastAPI server must be functional
- **Requires:** Story 4.2 (Autonomous Ship Rebuild Execution) — the Ship app must be rebuilt before it can be deployed
- **Requires:** A working Docker build (Story 1.1 scaffold includes Dockerfile)

### Previous Story Intelligence

- Story 1.6 established the FastAPI server with `POST /instruct` endpoint in `src/main.py`, running via uvicorn on port 8000.
- Story 1.1 created the Dockerfile and docker-compose.yml as part of the project scaffold.
- The architecture specifies Docker as the deployment unit with Railway as the target hosting platform.

### Project Structure Notes

- Dockerfile: `Dockerfile` (project root)
- Docker Compose: `docker-compose.yml` (project root)
- Entry point: `src/main.py` (FastAPI app)
- Ship app output: `{target_dir}/` (from Story 4.2)
- Environment template: `.env.example`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.1 — acceptance criteria]
- [Source: _bmad-output/planning-artifacts/epics.md#FR13 — Deployed Application requirement]
- [Source: _bmad-output/planning-artifacts/architecture.md — Docker + Railway deployment strategy]
- [Source: _bmad-output/implementation-artifacts/1-6-persistent-server-cli-entry-point.md — FastAPI server setup]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
