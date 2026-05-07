# How to set up a dev container that works well with Claude

A reusable target template for a Claude-friendly dev container,
grounded in the PawprintRecipes setup as a worked example (reliable
for months). The goal is to capture the **pattern** so you can copy
it to a new project and have a productive Claude-driven dev
environment in under an hour.

PawprintRecipes-specific names (`pawprintrecipes_backend` container,
`diane` user, the `PawprintRecipes` display name) appear throughout
as concrete examples — substitute your project's equivalents per the
"Adapting to a new project" checklist near the end.

The mental model:

- VSCode opens the repo "in" a Linux container
- The container has every tool you need pre-installed
- Your repo is bind-mounted, so edits are live both sides
- Your host's SSH keys are mounted, so git/deploy/ssh work
- Claude Code CLI is installed and its auth persists across rebuilds
- Sibling services (db, redis, web frontend, etc.) are reachable by
  hostname on a docker network
- Ports auto-forward to the host browser

The setup tested on **Windows 11 + WSL2 + Docker Desktop**, but the
same pattern works on macOS and native Linux — the only OS-specific
piece is one cross-platform path expression in `devcontainer.json`,
covered below.

---

## The four files that do all the work

```
.devcontainer/
  devcontainer.json              # VSCode config: mounts, extensions, post-create hook
docker/
  docker-compose.dev.yml         # services, networking, repo mount, .claude mount
{primary-service}/
  Dockerfile.dev                 # what's installed in the container Claude runs in
scripts/
  devcontainer-post-create.sh    # runs once after the image is built
```

Two things matter about this split:

1. **`.devcontainer/devcontainer.json` is the entry point.** VSCode's
   Dev Containers extension reads it and decides how to start
   everything. Without this file, none of the rest matters.
2. **The Dockerfile and the post-create script have different
   cache lifetimes.** Apt packages, JDK, language runtimes go in
   the Dockerfile so a rebuild is fast. `pip install -r requirements.txt`,
   npm globals, pre-commit hooks go in post-create so they re-run
   on rebuild but the underlying image stays cached.

---

## devcontainer.json — the spec VSCode reads

Annotated example from this project (`.devcontainer/devcontainer.json`):

```jsonc
{
  // Display name in the VSCode "running container" dropdown.
  "name": "PawprintRecipes - Full Project",

  // Compose-driven setup. The "service" is the container VSCode
  // attaches to (the one Claude lives in). Other services in the
  // compose file are siblings on the same docker network.
  "dockerComposeFile": ["../docker/docker-compose.dev.yml"],
  "service": "backend",
  "workspaceFolder": "/workspace",

  // Optional: pull in canned tool-installs maintained by the
  // devcontainer org. Cheaper than apt-installing yourself.
  "features": {
    "ghcr.io/devcontainers/features/node:1": { "version": "24" },
  },

  "customizations": {
    "vscode": {
      // Extensions auto-installed inside the container's VSCode
      // server. Putting them here means a fresh checkout has the
      // right tooling without anyone knowing what to install.
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "charliermarsh.ruff",
        "ms-python.mypy-type-checker",
        "ms-playwright.playwright",
        "anthropic.claude-code", // <-- Claude Code as a VSCode extension
      ],
      "settings": {
        "python.defaultInterpreterPath": "/usr/local/bin/python",
        "[python]": {
          "editor.defaultFormatter": "charliermarsh.ruff",
          "editor.formatOnSave": true,
          "editor.codeActionsOnSave": { "source.organizeImports": "explicit" },
        },
      },
    },
  },

  // Runs ONCE inside the container after the image is built or
  // rebuilt. See the post-create script section below.
  "postCreateCommand": "/workspace/scripts/devcontainer-post-create.sh",

  // VSCode operates as this user. MUST match the user the
  // Dockerfile creates (uid 1000).
  "remoteUser": "diane",

  // Bind mounts BEYOND what the compose file declares. This is
  // where your host's SSH keys come in.
  "mounts": [
    "source=${localEnv:HOME}${localEnv:USERPROFILE}/.ssh,target=/home/diane/.ssh,type=bind,consistency=cached",
  ],

  // Auto-forward these container ports to host loopback so your
  // browser on the host can hit dev servers.
  "forwardPorts": [3000, 8000, 8001, 5432, 6379],
  "portsAttributes": {
    "3000": { "label": "Web Frontend", "onAutoForward": "notify" },
    "8000": { "label": "Django Backend", "onAutoForward": "notify" },
    "8001": { "label": "Staff Panel", "onAutoForward": "notify" },
    "5432": { "label": "PostgreSQL", "onAutoForward": "silent" },
    "6379": { "label": "Redis", "onAutoForward": "silent" },
  },
}
```

### The single most important line

```json
"source=${localEnv:HOME}${localEnv:USERPROFILE}/.ssh,target=/home/diane/.ssh,..."
```

This bind-mounts your host's `.ssh` directory into the container.
`${localEnv:HOME}` resolves on Linux/macOS hosts; `${localEnv:USERPROFILE}`
resolves on Windows. By concatenating both, the unused variable
resolves to empty and the same line works on every host. **Without
this, no git over SSH, no `ssh user@host`, no deploys.**

The target path must match the user inside the container — change
`/home/diane/.ssh` if your container creates a different user.

---

## docker-compose.dev.yml — services + the magic mounts

Two mounts on the primary service do most of the persistence work.
From `docker/docker-compose.dev.yml`:

```yaml
backend:
  build:
    context: ../backend
    dockerfile: Dockerfile.dev
  container_name: pawprintrecipes_backend
  init: true # reaps zombies when child processes die
  ports: ["8000:8000"]
  volumes:
    - ..:/workspace # the entire repo, live
    - ../.claude:/home/diane/.claude # Claude auth state, gitignored
  env_file: ../.env
  environment:
    - DJANGO_SETTINGS_MODULE=config.settings.dev
    - DATABASE_URL=postgres://...@db:5432/...
    - REDIS_URL=redis://redis:6379/0
  depends_on:
    db: { condition: service_healthy }
    redis: { condition: service_healthy }
  networks: [pawprintrecipes_network]
  working_dir: /workspace
  command: sleep infinity # see "Why sleep infinity" below
```

### The `.claude` volume — the trick that makes Claude auth durable

```yaml
- ../.claude:/home/diane/.claude
```

This mounts a `.claude/` directory at the repo root onto the path
where the Claude Code CLI stores its auth state inside the container
(`~/.claude/`). Effects:

- **Auth survives container rebuilds.** Tear down + rebuild the
  container; your `gh auth login`-equivalent for Claude is still there.
- **Auth never gets baked into image layers** (which can persist
  long after you think they're gone).
- **Auth never gets committed** — `.claude/` is in `.gitignore` for
  this repo. Don't forget to add it to a new project's gitignore.

The same pattern works for any tool whose state you want to persist
without baking into the image: `~/.config/gh`, `~/.aws`, `~/.kube`,
etc. Just add another mount.

### Why `command: sleep infinity` on the dev container

Compose normally treats containers as "the application." For a dev
container, you want the container to stay alive as a _shell environment_
that Claude (and you) work inside — actual app servers (gunicorn,
`npm run dev`, etc.) get started on demand from inside the shell.
`sleep infinity` is the idiomatic way to say "stay running, don't
do anything."

### Sibling services

The compose file also declares `db` (postgres), `redis`, `web`
(Next.js dev server), `staff` (Django admin panel). They're on the
same docker network, so from inside the backend container you reach
them by hostname:

```bash
psql postgres://...@db:5432/...   # not localhost — db
redis-cli -h redis                # not localhost — redis
curl http://web:3000/             # not localhost — web
```

The `forwardPorts` list in `devcontainer.json` plus the `ports`
mappings on individual services let your host browser see the same
things via `localhost:3000`, `localhost:8000`, etc.

---

## Dockerfile.dev — what to install

Three layers, in order of how often they change:

```dockerfile
# 1. Base image — pick the one closest to your primary stack
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 2. OS-level tools you'll always want
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl wget git sudo \
    openssh-client rsync gnupg2 unzip \
    && rm -rf /var/lib/apt/lists/*

# 3. Project-specific tooling. Add what you build/release.
#    For Pawprint: JDK 21 + Android SDK because we build Android APKs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

ENV ANDROID_HOME=/opt/android-sdk
ENV PATH="${PATH}:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools"
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
        -O /tmp/cmdline-tools.zip && \
    unzip -q /tmp/cmdline-tools.zip -d ${ANDROID_HOME}/cmdline-tools && \
    mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest && \
    rm /tmp/cmdline-tools.zip
RUN yes | sdkmanager --licenses > /dev/null 2>&1 && \
    sdkmanager "platforms;android-35" "build-tools;35.0.0" "platform-tools"

# GitHub CLI — useful for any Claude-driven workflow that touches
# PRs, issues, or releases.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# 4. Create the user VSCode + Claude run as. Match uid 1000 so
#    bind-mounted files have correct ownership without chown gymnastics.
RUN groupadd -g 1000 diane && \
    useradd -m -u 1000 -g diane -s /bin/bash diane && \
    echo "diane ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /workspace

# 5. Install Python deps that won't change every commit. Project
#    deps that DO change go in the post-create script.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN chown -R diane:diane /workspace
USER diane

EXPOSE 8000
CMD ["python", "backend/manage.py", "runserver", "0.0.0.0:8000"]
```

### Why uid 1000

On most Linux and WSL2 systems your host user is uid 1000. Matching
that uid for the in-container user means files written by the
container in the bind-mounted workspace look like _yours_ on the
host — no `chown -R` needed after every container rebuild.

If your host user has a different uid, change the `1000` in the
`groupadd`/`useradd` lines to match. Run `id -u` on the host to
check.

### Why NOPASSWD sudo

Apt-installing things from the post-create script needs root. The
container is throwaway and yours alone, so passwordless sudo is
fine — no security boundary is being weakened.

---

## scripts/devcontainer-post-create.sh — the one-time setup

This runs once after every container build/rebuild, as the user
VSCode is attaching as. Things that change with the repo go here so
you don't have to rebuild the image to pick them up.

```bash
#!/bin/bash
set -e

LOG_DIR="/workspace/logs/devcontainer"
LOG_FILE="$LOG_DIR/post-create_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$LOG_DIR"

{
    sudo apt-get update
    sudo apt-get install -y jq                       # whatever else changes infrequently

    # Make sure git inside the container trusts the bind-mounted repo
    git config --global --add safe.directory /workspace

    pip install --upgrade pip
    pip install -r /workspace/backend/requirements.txt

    # Dev-only Python tooling (lives outside requirements.txt so
    # production images don't pull it).
    pip install pytest pytest-django pytest-cov pytest-xdist \
                pytest-rerunfailures playwright ruff mypy bandit

    # Claude Code CLI, installed globally so it's on PATH everywhere
    # in the container.
    npm install -g @anthropic-ai/claude-code

    # Pre-commit hooks: install + activate
    pip install pre-commit
    (cd /workspace && pre-commit install)

    # Browser for any Playwright-driven UI tests
    playwright install chromium
    sudo PYTHONPATH="/home/diane/.local/lib/python3.14/site-packages" \
        /usr/local/bin/python -m playwright install-deps chromium

} 2>&1 | tee "$LOG_FILE"

ln -sf "$LOG_FILE" "$LOG_DIR/post-create_latest.log"
```

A few patterns worth keeping:

- **Tee the output to a timestamped log under `logs/devcontainer/`.**
  When something fails on a rebuild, the log tells you which step
  blew up. Symlink `post-create_latest.log` to the most recent run
  so you don't have to grep filenames.
- **`git config --global --add safe.directory /workspace`** — git
  refuses to operate in directories it thinks are owned by another
  user, which is what bind mounts often look like to it. This line
  whitelists the workspace.
- **`pre-commit install`** activates hooks defined in
  `.pre-commit-config.yaml`. Without this line, hooks defined in
  the repo silently don't run.

---

## Authentication: how each tool's auth survives

The devcontainer rebuild is the moment auth state is most likely to
get lost. Here's where each tool keeps its state and how it survives
this project's setup:

| Tool                                                      | State location inside container                    | How it survives rebuilds                                                                        |
| --------------------------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **SSH** (git over SSH, deploy SSH, etc.)                  | `/home/diane/.ssh/`                                | Bind-mounted from host's `~/.ssh` via `devcontainer.json` `mounts`                              |
| **Claude Code CLI**                                       | `/home/diane/.claude/` (state, history, MCP cache) | Bind-mounted to `.claude/` in the repo via the compose volume; gitignored                       |
| **GitHub CLI (`gh`)**                                     | `/home/diane/.config/gh/`                          | Not persisted in this setup — run `gh auth login` once after each rebuild, OR add another mount |
| **Git**                                                   | `~/.gitconfig` + per-repo `.git/config`            | `.gitconfig` is per-container; per-repo config persists via the workspace mount                 |
| **Anything else** (kubectl, aws, gcloud, npm token, etc.) | Their own `~/.config/<tool>` or `~/.<tool>` dirs   | Add a bind mount in `devcontainer.json` or a volume in the compose file                         |

The pattern for adding a new auth-persisting mount:

1. Find where the tool stores state on Linux. Usually `~/.config/<tool>/`
   or `~/.<tool>/` — `strace` or the tool's docs will tell you.
2. Decide where the state should live on the host:
   - **In the repo** (gitignored) — like `.claude/`. Pros: tied to
     the project, auto-restored on a fresh checkout. Cons: only one
     auth per repo per machine.
   - **In your home dir on the host** — like `~/.ssh`. Pros: shared
     across all your projects. Cons: you have to set it up per
     machine.
3. Add the mount in `devcontainer.json` (for paths under `~/`) or
   the compose `volumes:` block (for paths in the repo).

---

## Adapting to a new project — the checklist

Copy `.devcontainer/`, `docker/`, `scripts/devcontainer-post-create.sh`,
and the `Dockerfile.dev` for your primary service. Then customize:

1. **`devcontainer.json`**:
   - Change `name` to your project
   - Change `service` if your primary container is named something else
   - Update `extensions` for your stack
   - Update `forwardPorts` for your dev server ports
   - **Update `/home/diane/` paths** if your container's user isn't
     called `diane`
2. **`docker-compose.dev.yml`**:
   - Rename services (`pawprintrecipes_*`)
   - Strip out services you don't need (no Redis? delete it)
   - Update mount paths (the `.claude` mount target must match the
     container user)
   - Update env_file path to your `.env`
3. **`Dockerfile.dev`**:
   - Change base image to your stack's minimum
   - Drop tooling you don't need (no Android? drop JDK + SDK)
   - Add tooling you do (Rust toolchain? Go? CUDA?)
   - **Update the username in `groupadd`/`useradd`** to match
     `remoteUser` and the mount targets
4. **`devcontainer-post-create.sh`**:
   - Change the `pip install -r requirements.txt` line to point at
     your deps file (or replace with `npm install`, `cargo build`,
     etc.)
   - Drop steps you don't need (no Playwright? drop the chromium step)
5. **`.gitignore`**:
   - Add `.claude/` (essential — Claude state must not be committed)
   - Add `.env`, `.env.local`, etc. (if not already)
   - Add `logs/devcontainer/` if you keep the post-create logging
     pattern
6. **First boot**:
   - `gh auth login` (one time per rebuild, unless you add a mount)
   - `git config --global user.email/user.name` (if `~/.gitconfig`
     isn't mounted from host)
   - Verify Claude auth: open the Claude Code extension; if you're
     prompted to log in, do so. The mount means you only do this
     once per machine.

---

## Common pitfalls and how to avoid them

| Symptom                                                                                            | Cause                                                                                                                 | Fix                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Permission denied (publickey)` on git over SSH inside the container                               | The SSH bind mount didn't resolve — your host's `${localEnv:HOME}` is empty (or `${localEnv:USERPROFILE}` on Windows) | Use the cross-platform `${localEnv:HOME}${localEnv:USERPROFILE}` form. Verify the key file exists in `/home/<user>/.ssh/` after attach.                                |
| Files written by the container show as owned by `1000:1000` on the host but with weird permissions | Host user uid is not 1000                                                                                             | Change the Dockerfile's `groupadd -g 1000`/`useradd -u 1000` to match `id -u` on your host                                                                             |
| `git status` says "fatal: detected dubious ownership" inside the container                         | Missing safe-directory whitelist                                                                                      | `git config --global --add safe.directory /workspace` in post-create                                                                                                   |
| Claude Code asks you to log in every time you rebuild                                              | `.claude/` mount missing or pointed at the wrong path                                                                 | Verify the compose volume target matches the container user's `~/.claude/`                                                                                             |
| Apt commands prompt for a password during post-create and hang                                     | NOPASSWD sudo not set up                                                                                              | Add `echo "${USER} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers` in the Dockerfile                                                                                          |
| Container exits immediately after build                                                            | `command:` runs the actual app and the app crashed                                                                    | Use `command: sleep infinity` for the dev container; start the app server manually when you need it                                                                    |
| `Cannot connect to the Docker daemon` from inside the container                                    | Docker CLI installed inside but no socket forwarded                                                                   | Don't put the Docker CLI inside the dev container. Run `docker compose` from the host instead. (This is what Pawprint does — `docker` is intentionally absent inside.) |
| Sibling services unreachable by hostname                                                           | Containers not on the same docker network                                                                             | Add `networks: [<project>_network]` to every service in the compose file and define the network at the bottom                                                          |
| Zombie processes accumulate over a long session                                                    | Missing `init: true` on the dev service                                                                               | Add `init: true` so docker reaps orphans                                                                                                                               |
| `apt-get install` warns about "no GPG key" or "expired key"                                        | Stale apt cache from when the image was built months ago                                                              | Either rebuild the image (the Dockerfile re-fetches) or `sudo apt-get update` early in the post-create script                                                          |

---

## What this setup deliberately does NOT do

A few things you might expect that this setup leaves out, on purpose:

- **No Docker CLI inside the container.** The dev container is for
  _editing and running app code_, not for managing other containers.
  Putting Docker inside Docker invites confusion about which daemon
  you're talking to. If you need to run `docker compose` against the
  dev stack, do it from the host's WSL2/macOS/Linux terminal.
- **No bake of secrets into the image.** Anything sensitive (API
  keys, signing certs, DB passwords) lives either in `.env` (mounted
  via `env_file`), in `~/.ssh` (bind-mounted), or in `.claude/`
  (bind-mounted). Image layers are immutable and persistent — they
  are the wrong place for secrets.
- **No global `git config --global user.*`** in the Dockerfile. Use
  the host's gitconfig, mounted in, or set it once per rebuild. The
  Dockerfile shouldn't know your name and email.
- **No persistent shell history.** Add a bind mount of `~/.bash_history`
  if you want it, but most Claude-driven workflows don't need it.

---

## Reference: what gets you a working setup the first time

If you want a "smoke test" sequence after you've set everything up:

```bash
# 1. From host, build + start
cd /path/to/repo
code .                      # opens VSCode, prompts to reopen in container

# 2. Once attached (you're now inside the container), verify
whoami                      # should be the user from the Dockerfile
pwd                         # should be /workspace
ls ~/.ssh                   # should show your host SSH keys
ls ~/.claude                # should show .credentials.json (if Claude has been logged in)
which claude                # should be /usr/local/bin/claude or similar
gh auth status              # tells you whether gh is logged in
git status                  # should not complain about ownership

# 3. Network from inside the container
ping -c 1 db                # sibling service hostnames resolve
curl http://localhost:8000/api/v1/health/   # only works if the app is running
```

If all of those pass, the container is set up correctly and Claude
should be productive immediately.
