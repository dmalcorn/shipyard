# Git Remote Setup Guide for Shipyard Factory Runs

## Overview

When Shipyard's rebuild pipeline creates a new project, it runs `git init` in the target directory, commits code as stories complete, and pushes to configured remotes. This guide covers how to set up GitHub (and optionally GitLab) remotes so that pushes land correctly and downstream services (like Railway) deploy from the right branch.

## How the Pipeline Works

1. `init_project_node` runs `git init` in the target directory
2. Git defaults to creating a branch called `master` (unless the system has `init.defaultBranch` configured otherwise)
3. The pipeline commits after each story and pushes to `origin` using `git push origin <branch> --tags`
4. The branch name is auto-detected via `git rev-parse --abbrev-ref HEAD`

## The Branch Name Problem

GitHub and GitLab both default new repos to `main` as the default branch. But `git init` on most systems defaults to `master`. This means:

- The pipeline pushes to `master`
- GitHub/GitLab repos have `main` as their default branch
- Services like Railway deploy from the default branch (`main`), which is empty or stale
- Manual pushes from the target directory may go to `main` (the remote default), creating a divergent branch

## Pre-Run Setup Checklist

### 1. Create the remote repos

Create empty repos on GitHub and/or GitLab. **Do not** initialize them with a README, .gitignore, or license -- the pipeline will create its own initial commit.

### 2. Set the default branch on the remote to `master`

Since the pipeline creates `master` locally, the simplest approach is to match the remote:

**GitHub:**
- Go to the repo > Settings > General > Default branch
- After the first push lands, change the default branch from `main` to `master`
- Delete the `main` branch if it was auto-created

**GitLab:**
- Go to the repo > Settings > Repository > Branch defaults
- Set default branch to `master`

Alternatively, you can change the default branch name for all new repos in your GitHub/GitLab account settings, but that affects every repo you create.

### 3. Configure `.env` with auth tokens

The pipeline runs inside Docker where there is no credential helper. Remote URLs must include auth tokens:

```
GIT_REMOTE_ORIGIN=https://<github-pat>@github.com/<user>/<repo>.git
GIT_REMOTE_MIRROR=https://oauth2:<gitlab-pat>@labs.gauntletai.com/<user>/<repo>.git
```

**GitHub:** Generate a fine-grained personal access token with `Contents: Read and write` permission scoped to the specific repo.

**GitLab:** Generate a project access token with `read_repository` and `write_repository` scopes. The URL format requires `oauth2:` before the token.

### 4. Verify token access before starting

Test from your terminal before running the pipeline:

```bash
git ls-remote https://<token>@github.com/<user>/<repo>.git
git ls-remote https://oauth2:<token>@labs.gauntletai.com/<user>/<repo>.git
```

Both should return refs (or an empty list for a new repo) without prompting for credentials.

### 5. Configure Railway (if deploying from this repo)

- Link the Railway service to the GitHub repo
- Set the deploy branch to `master` in Railway service Settings > Source
- Or wait until the first push lands, then verify Railway detects the correct branch

## If Something Goes Wrong

### Pipeline pushed to `master` but Railway deploys from `main`

Change Railway's deploy branch to `master`, or push master to main:

```bash
git push origin master:main --force
```

### Manual push created a divergent `main` branch

If you cd into the target directory and run `git push` manually, git may push to the remote's default branch (`main`) instead of `master`. Always specify the branch:

```bash
git push origin master
```

Or delete the stale `main` branch on the remote:

```bash
git push origin --delete main
```

### Token exposed in logs

The pipeline redacts tokens from log output, but if a token is exposed:

1. Revoke the token immediately on GitHub/GitLab
2. Check Railway database for exposed log events and delete them
3. Generate a new token and update `.env`

## Future Improvement

A one-line change to the pipeline (`git init -b main`) would make the local branch match GitHub/GitLab defaults, eliminating the branch mismatch entirely. This is tracked but not yet implemented to avoid mid-run changes.
