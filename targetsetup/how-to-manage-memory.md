# How to manage Claude Code memory

> **TL;DR** — Memory files live in the repo at [`.claude/memory/`](../.claude/memory/). On Windows, a directory junction at `~/.claude/projects/<mangled-path>/memory` makes Claude Code see them transparently. When you move the repo to a new machine via flash drive, **recreate the junction once** (one PowerShell command, takes 5 seconds). This document is the survival guide.

---

## Why this matters

This pattern is for projects that want their Claude Code memory to live inside the repo (so it travels with flash-drive copies, gets backed up alongside code, and is portable across machines) rather than at Claude Code's default user-home location. PawprintRecipes adopted it on 2026-05-05; this document is the reusable template, with PawprintRecipes paths as worked examples.

By default, Claude Code stores memory at `~/.claude/projects/<mangled-path>/memory/` — **outside** any repo. That's fine for most users, but it breaks two things projects with portability needs care about:

1. **Repo portability** — copying the repo to a flash drive doesn't include memory. The new machine has no access to past project context.
2. **Backup unity** — backing up the repo doesn't back up memory. They drift apart over time.

The fix: memory files **live in the repo** at `.claude/memory/`. A Windows directory junction at the user-home path transparently redirects Claude Code to the in-repo location. Net result:

- ✅ Memory travels with the repo via flash drive (or any copy mechanism)
- ✅ Backups capture memory as part of the repo
- ✅ Claude Code reads / writes memory normally — the junction is invisible to it
- ✅ No global Claude Code settings change required (other projects on this machine continue to use the default `~/.claude/...` location)

---

## Current architecture

```
┌─────────────────────────────────────────────────────────┐
│ ACTUAL FILES                                            │
│ <repo>/.claude/memory/                                  │
│   ├── MEMORY.md                                         │
│   ├── feedback_*.md                                     │
│   ├── project_*.md                                      │
│   └── ... (one file per memory entry)                   │
└─────────────────────────────────────────────────────────┘
                         ▲
                         │ Windows directory junction
                         │ (mklink /J — no admin required)
                         │
┌─────────────────────────────────────────────────────────┐
│ JUNCTION (where Claude Code looks)                      │
│ ~/.claude/projects/<mangled-path>/memory                │
│   → transparent pointer to <repo>/.claude/memory/       │
└─────────────────────────────────────────────────────────┘
```

The `<mangled-path>` is Claude Code's encoding of the project's absolute filesystem path. Slashes, colons, and other separators become `--`. For example, `c:\alcorn\AI\PawPrintRecipes-wrapper\PawprintRecipes` becomes `c--alcorn-AI-PawPrintRecipes-wrapper-PawprintRecipes`. **The mangled path differs across machines because the absolute path differs.**

The in-repo location (`<repo>/.claude/memory/`) is stable and portable. The user-home junction location is machine-specific and recreated per machine.

---

## When to use this setup

✅ **Use the in-repo + junction setup when:**

- You move the repo across machines (flash drive, cloud sync, repo clone)
- You want backups of the repo to include memory automatically
- You're a solo operator and don't need per-user memory diversity

⚠️ **Don't use this setup when:**

- Multiple users collaborate on the same repo and each wants their own memory (e.g., team project on shared git repo). Their memories would conflict at the same in-repo location.
- You're on macOS / Linux and don't want to deal with symlinks. (The principle works there too — use `ln -s` instead of `mklink /J` — but the syntax differs.)

---

## Cross-machine transfer procedure

### Scenario: moving this repo from Laptop A to Laptop B via flash drive

#### On Laptop A (source — before transfer)

Nothing to do. The memory files are already inside the repo at `.claude/memory/`. The flash drive copy will include them automatically.

> 💡 If you've made memory changes recently and want to make sure they're flushed to disk: just close the active Claude Code session (writes are flushed at end-of-session). Then copy the repo to the flash drive.

#### Copy to flash drive

Standard copy. Include the entire repo. The `.claude/memory/` directory inside the repo travels with it. Don't worry about the user-home junction location on Laptop A — it points at the in-repo files but isn't part of the transfer.

#### On Laptop B (destination — after transfer)

After copying the repo to its new location on Laptop B (let's call that `<NEW-REPO-PATH>`), run **once** to recreate the junction:

```powershell
# Replace <NEW-REPO-PATH> with the actual absolute path of the repo on Laptop B,
# e.g. "D:\projects\PawprintRecipes" or wherever you put it.

$repoPath  = "<NEW-REPO-PATH>"
$drive   = $repoPath.Substring(0, 1).ToLower()         # "C" -> "c" (drive letter must be lowercase)
$rest    = $repoPath.Substring(2) -replace '\\', '-'   # skip the ':' at index 1; convert backslashes to '-'
$mangledPath = "$drive-$rest"                          # join with "-"; combined with leading "-" of $rest gives "--"
# Mangling rules:
#   1. Lowercase the drive letter
#   2. Replace ':' with '-' (so "c:" becomes "c-")
#   3. Replace each '\' with '-' (the leading '\' after the drive becomes another '-', giving "c--")
# Example: "C:\alcorn\AI\PawprintRecipes" -> "c--alcorn-AI-PawprintRecipes"
#
# Note on case: Windows filesystems are case-INSENSITIVE for directory names, so minor case
# differences between this computed name and what Claude Code shows in ~/.claude/projects/
# are harmless — the junction works either way. If the formula and reality don't match
# even case-insensitively, use Method 1 below.

$junctionDir = "$env:USERPROFILE\.claude\projects\$mangledPath"
$junctionPath = Join-Path $junctionDir "memory"

# Make sure the parent directory exists; Claude Code may not have run yet on this machine
New-Item -ItemType Directory -Force -Path $junctionDir | Out-Null

# If a memory directory was already created (e.g., from a prior Claude Code session
# starting fresh), back it up rather than overwrite
if (Test-Path $junctionPath) {
    Move-Item $junctionPath "$junctionPath.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}

# Create the junction
cmd /c mklink /J "$junctionPath" "$repoPath\.claude\memory"

# Verify
Write-Output "[Junction created at: $junctionPath]"
Write-Output "[Pointing to: $repoPath\.claude\memory]"
Get-ChildItem $junctionPath | Select-Object Name, Length | Format-Table
```

**Verification:** the `Get-ChildItem` at the end should list `MEMORY.md` plus the various `project_*.md` and `feedback_*.md` files. If it does, you're done — Claude Code will read memory from the in-repo location transparently.

---

## Discovering the mangled path manually

If the PowerShell mangling formula above gives wrong results (Claude Code's exact mangling rules can change between versions), find the right path another way:

### Method 1: run Claude Code once first

Open the project in Claude Code and trigger any session. Claude Code will automatically create `~/.claude/projects/<correct-mangled>/` (with whatever subdirectories its current version uses). Then `ls ~/.claude/projects/` to find the new directory name.

Once you know the mangled name, delete any auto-created `memory/` subdirectory inside it (it'll be empty since the real memory is in the repo) and replace it with the junction.

### Method 2: ask Claude Code

In a fresh session, ask Claude where it's writing memory. The system context will reveal the exact path. Use that.

---

## Worked example: layout on the original setup machine (PawprintRecipes, 2026-05-05)

After the in-session setup ran:

| Path                                                                                              | What it is                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `C:\alcorn\AI\PawPrintRecipes-wrapper\PawprintRecipes\.claude\memory\`                            | **Actual memory files** (the source of truth; backed up by repo backups; portable via flash drive)                                                                   |
| `C:\Users\Diane\.claude\projects\c--alcorn-AI-PawPrintRecipes-wrapper-PawprintRecipes\memory`     | **Junction** pointing to the in-repo path. Claude Code reads/writes here; everything is transparently redirected.                                                    |
| `C:\Users\Diane\.claude\projects\c--alcorn-AI-PawPrintRecipes-wrapper-PawprintRecipes\memory.bak` | **Pre-junction backup** of the original user-home memory files (8 files copied 2026-05-05). Safe to delete once you've verified everything works for a few sessions. |
| `C:\Users\Diane\.claude\projects\<other-projects-mangled>\memory\`                                | Other Claude Code projects' memory — **untouched** by this setup. Each project has its own memory directory; this setup only modified the PawprintRecipes one.       |

---

## Verification checks

After setup (or after recreating the junction on a new machine):

```powershell
$junctionPath = "$env:USERPROFILE\.claude\projects\<your-mangled-path>\memory"

# Check 1: the path exists
Test-Path $junctionPath
# Should output: True

# Check 2: it's a junction, not a regular directory
(Get-Item $junctionPath -Force).LinkType
# Should output: Junction

# Check 3: it points to the right target
(Get-Item $junctionPath -Force).Target
# Should output: C:\path\to\repo\.claude\memory

# Check 4: memory files are visible through it
Get-ChildItem $junctionPath
# Should list MEMORY.md and the various project_*.md / feedback_*.md files

# Check 5: writes through the junction land in the repo
"test" | Out-File "$junctionPath\write-test.txt"
Test-Path "C:\path\to\repo\.claude\memory\write-test.txt"
# Should output: True
Remove-Item "$junctionPath\write-test.txt"   # cleanup
```

If all 5 checks pass, the junction is working correctly.

---

## Cleaning up

The pre-junction backup at `<user-home>/memory.bak/` (created on the original setup machine) is a safety net. Once you've verified Claude Code reads/writes memory correctly through the junction across **a few sessions** — say a week of normal use — the `.bak` directory is safe to delete:

```powershell
Remove-Item "C:\Users\Diane\.claude\projects\c--alcorn-AI-PawPrintRecipes-wrapper-PawprintRecipes\memory.bak" -Recurse -Force
```

On a fresh new-machine setup (Method 1 above with the auto-`Move-Item` to a timestamped backup), the same cleanup applies — verify a week, then delete the `*.bak-<timestamp>` directory.

---

## Alternative: the `autoMemoryDirectory` settings approach

For completeness, Claude Code also supports an `autoMemoryDirectory` setting in `~/.claude/settings.json`:

```json
{
  "autoMemoryDirectory": "C:/path/to/some/memory/root"
}
```

This setting is **global per-machine** (only accepted in user-level `~/.claude/settings.json`, not in any in-repo settings file — security restriction). It also still applies the per-project mangled-path subfolder, so memory ends up at `<custom-root>/<mangled-path>/`.

**Why we don't use this for PawprintRecipes:**

- It's global. If you set `autoMemoryDirectory` to a path inside this repo, **other Claude Code projects on the same machine would also write their memory inside this repo** (under their own mangled-path subfolders). Awkward.
- The mangled subfolder still applies, so cross-laptop transfer would still need a manual rename of the mangled folder on the new machine.

The junction approach we use is per-project (only this repo gets it), needs no global setting changes, and produces files at a stable in-repo path that's identical across machines (only the junction location changes per machine).

---

## What if something breaks?

### "Claude Code can't find memory"

Check the junction:

```powershell
Test-Path "C:\Users\Diane\.claude\projects\c--alcorn-AI-PawPrintRecipes-wrapper-PawprintRecipes\memory"
```

If `False`: the junction is missing. Recreate it (see "On Laptop B" procedure above).

If `True` but Claude Code still doesn't see memory: check the LinkType is `Junction` and Target is correct (Verification check above). If LinkType is empty/null, the path is a regular directory (not a junction) and Claude is reading whatever's there — probably an empty dir Claude Code auto-created. Delete it, then recreate the junction.

### "I deleted memory.bak too early and the in-repo files got corrupted"

Check repo backups (you should have backups of the repo). The in-repo `.claude/memory/` is just regular files — restore from any backup.

### "I need to start over from scratch on a new machine"

If you don't have memory files from the original (no flash drive, no backup): just run Claude Code on the new machine. Memory builds up over time as the agent learns about the project. Read `MEMORY.md` will be empty until the first save; that's fine.

### "I want to switch to using `autoMemoryDirectory` instead of the junction"

Up to you. Procedure: (1) set `autoMemoryDirectory` in `~/.claude/settings.json`, (2) move files from `<repo>/.claude/memory/` to the new location (under the mangled subfolder), (3) delete the junction. See the alternative-approach section above for caveats.

---

## See also

- [`README.md`](../README.md) — repo-level overview
- [`CLAUDE.md`](../CLAUDE.md) — Claude Code project context (the auto-loaded file)
- Claude Code memory docs: <https://code.claude.com/docs/en/memory.md>
