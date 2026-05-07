# How to Write Epics for Android vs iOS

A reference for the PM agent (or human author) drafting mobile epics. Captures the strategic differences between Android and iOS user behavior and how those differences should shape Android and iOS epics — and any future mobile epics — without bloating either epic.

**Companion doc:** [`how-to-write-epics.md`](how-to-write-epics.md) covers the 13 structural patterns that apply to _all_ epics (web and mobile). This doc covers what's specific to mobile.

**Source of patterns:** distilled from PawprintRecipes Epic 16 (Android) + Epic 17 (iOS) scoping (2026-05-05). Project-specific examples — story numbers, FR numbers, UX-DR numbers, approved versions, hardware names — are kept throughout as illustrative case studies; future projects swap in their own specifics or treat the existing ones as historical illustration.

---

## 1. The web marketing site does NOT mirror to mobile screens

The web marketing homepage (and SEO infrastructure — sitemap, SSR recipe pages) exists to be **findable by Google** and convert anonymous visitors into registered users. That entire purpose is web-specific.

Mobile apps:

- Don't do SEO
- Don't have anonymous browser visitors
- Get discovered through different surfaces (App Store search, Play Store search, web→store badge clicks)

So the marketing-site → mobile mapping is a **store-listing handoff**, not a screen-to-screen mirror.

_Example mapping (PawprintRecipes):_

| Web marketing surface                       | Mobile equivalent                                               | Where it lives                                 |
| ------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------- |
| Marketing homepage (Story 4.5)              | App store listing — screenshots, description, app preview video | Play Store / App Store metadata (NOT app code) |
| SEO sitemap + recipe SSR (Stories 4.7, 4.9) | App store search optimization (ASO) keywords                    | Play Store / App Store metadata                |
| Public recipe browse (Story 4.6, anonymous) | Behind-login only on mobile                                     | No equivalent screen needed                    |
| Print-friendly recipe (Story 4.8)           | Doesn't apply on phones                                         | No equivalent                                  |
| Vet disclaimer footer                       | In-app About / Settings page                                    | Polish story or Settings story                 |
| Side-by-side recipe compare (FR35)          | Web-only (explicitly tagged in PRD)                             | No equivalent                                  |

**Implication for the PM author:** when drafting a mobile epic, do NOT add a story for "mobile marketing homepage" or "mobile SEO." Those concepts don't translate. The store listing is the closest analog, and it's its own story (see §4 below).

---

## 2. Android vs iOS user discovery differences

User journey _into_ the app differs between platforms. This shapes how much "sales pitch" the app needs to do internally.

### Android user journey (typical)

1. Discovers the brand via Google search → lands on web marketing site
2. Reads value proposition on the web
3. Clicks "Get on Google Play" badge in the hero or final CTA
4. Installs from Play Store
5. Opens app already understanding what it does

**Implication:** the Android first-launch experience can be lean — assume some prior context.

### iOS user journey (typical)

1. Discovers the app via App Store search, browse, or "Apps We Love" recommendations
2. Sees only the App Store listing (screenshots, description, app preview video)
3. Taps "Get" without much context
4. Opens app cold — needs to be sold _inside_ the app on first launch

**Implication:** the iOS first-launch needs to be slightly more polished than Android. Apple App Store Review Guideline 4.2 effectively _requires_ the app to demonstrate value before any paywall — Apple has rejected apps that put login/paywall as the first screen with no context.

### Both apps need a first-launch experience anyway

Even though the journeys differ in shape, both apps need a brief first-launch onboarding because:

1. Some Android users _will_ discover via Play Store search directly (they exist)
2. Some iOS users _will_ arrive having seen the web site (they exist)
3. App Store Review Guideline 4.2 requires it for iOS regardless

**Recommended pattern:**

- Android: a 2–3 screen onboarding carousel (e.g., "What this app does in 3 cards") → Sign in / Create account. Lean — assumes some prior context.
- iOS: the _same_ first-launch carousel, possibly with one extra screen demonstrating the core feature in action (a "see it work" demo card) for App Store Review compliance and cold discovery. Cited as "extends Story 16.X first-launch with iOS-specific demo screen."

The carousel is essentially the mobile-native _replacement_ for the web marketing site for users who arrived without context — abbreviated to fit a phone screen.

---

## 3. Store listings as their own story (NOT just engineering)

Every mobile epic gets one story dedicated to the platform store listing. Not every story needs to be code.

**What goes in a store-listing story:**

- App name, subtitle, category
- Short description (Play Store) / promotional text (App Store)
- Long description with feature highlights and core-value copy
- Screenshots (per device size — phone, tablet, watch where applicable)
- App preview video (App Store) / promo video (Play Store)
- Keywords / ASO terms
- Contact info, support URL, privacy policy URL
- Age rating questionnaire answers
- Localization (if multi-language launches are planned)

**Acceptance criteria pattern:**

- **Given** the marketing copy from the web marketing homepage story,
- **When** the store listing is prepared,
- **Then** the description references the same core value props as the PRD,
- **And** screenshots match the actual app screens from earlier mobile stories,
- **And** the App Store / Play Store listing passes review on first submission.

**Story tags:** `[infra]` + `[docs]` (or `[content]` if added). It's largely content-deliverables and store metadata config, not engineering — but it has concrete acceptance criteria and is part of the epic demo.

**Operator handoff:** the operator (or marketing collaborator) produces the screenshots and copy; the engineering work is just submitting via App Store Connect / Play Console.

---

## 4. The web ↔ mobile cross-cut at epic-end

When a mobile epic ships, the web marketing site needs to flip its store badges from "coming-soon" placeholders to the real store URLs.

_Example source (PawprintRecipes):_ PRD line 1312 — "the marketing homepage has prominent App Store / Google Play download badges in hero and final CTA. The badges link to a coming-soon page until Phase 2/3 ship."

**Pattern:** the mobile epic's Polish story (16.M / 17.M) includes a same-commit cross-cut that updates the web marketing homepage badge URLs to point to the real Play Store / App Store listings.

_Example cross-cut entry (PawprintRecipes Epic 16 header):_

> "Story 16.M (Polish) updates Story 4.5's web marketing homepage Play Store badge URL from coming-soon page to the real Play Store listing. Same-commit cross-cut."

Same pattern at end of the iOS epic for the App Store badge.

---

## 5. Mobile-specific FRs (Phase 2/3)

Some FRs apply ONLY to mobile. These are additions on top of the web FR set, and they each need a mobile epic story.

_Example FR cross-walk (PawprintRecipes — PRD §9.17):_

| FR    | What                                                                | Phase               | Where it slots                                                                      |
| ----- | ------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------- |
| FR106 | Mobile home renders Segment A/B/C/D layouts                         | Android P2 / iOS P3 | Mobile home story (16.4 / 17.4)                                                     |
| FR107 | Mobile home consumes `GET /api/v1/home/` per PRD §8.2–8.5 contracts | Android P2 / iOS P3 | Mobile home story (16.4 / 17.4) — drives `/api/v1/home/` upstream addition per §3.4 |
| FR108 | Cook Mode — step-by-step recipe walkthrough with timers             | Android P2 / iOS P3 | Dedicated Cook Mode story (16.6 / 17.6); UX-DR23 + UX-DR28                          |
| FR109 | Push notifications via FCM (Android) / APNs (iOS)                   | Android P2 / iOS P3 | Notifications story (16.11 / 17.11)                                                 |
| FR110 | DNA file capture via camera                                         | Android P2 / iOS P3 | DNA story (16.10 / 17.10) extends web DNA upload                                    |
| FR111 | Contextual permission requests with benefit explanation             | Android P2 / iOS P3 | Permissions / first-launch story (16.14 / 17.14)                                    |
| FR112 | App Store / Play Store policy compliance                            | Android P2 / iOS P3 | First-launch / store-listing stories                                                |
| FR113 | Permission table (Camera, Location, Push, Photos)                   | Android P2 / iOS P3 | Permissions / first-launch story (16.14 / 17.14)                                    |

All other FRs (the web set) carry phase tags `Web P1; Android P2; iOS P3` — the mobile epics implement mobile-native versions of those, sliced into vertical-slice stories.

**General rule:** any FR that fundamentally requires a mobile capability (camera, push, native billing, native sign-in, OS-level permissions) gets its own mobile-epic story. FRs that mirror web functionality get sliced by feature area.

---

## 6. Native technology stack

This must be binding from `approved-software-versions.md` and `architecture.md` — no substitutions. The choices below are PawprintRecipes' picks; future projects pick their own per their architecture decisions.

### Android (example: PawprintRecipes Epic 16)

| Concern              | Choice                                                                      | Notes                                           |
| -------------------- | --------------------------------------------------------------------------- | ----------------------------------------------- |
| Language             | Kotlin 2.3.10                                                               | Coroutines for async. Released Feb 4, 2026      |
| UI framework         | Jetpack Compose 1.10.1                                                      | Declarative, Material 3 theming                 |
| State management     | Compose + StateFlow + ViewModels                                            | Google's recommended pattern                    |
| Networking           | Retrofit + Kotlin Coroutines                                                | Type-safe API clients                           |
| Local storage        | Room                                                                        | Jetpack persistence; offline cache              |
| Sign-in              | Google Sign-In SDK (native)                                                 | Apple Sign-In via web fallback                  |
| Push                 | FCM directly                                                                |                                                 |
| Billing              | Google Play Billing Library v6+                                             |                                                 |
| Unit testing         | JUnit 4.13.2                                                                | Pure Kotlin, no UI                              |
| UI-component testing | Compose Test (`androidx.compose.ui.test`)                                   | Pairs with Compose UI                           |
| E2E testing          | Maestro CLI — local install on Windows host (Scoop or PowerShell installer) | Cross-platform YAML flows reused on iOS; see §7 |
| Min SDK              | API 29 (Android 10+)                                                        |                                                 |

### iOS (example: PawprintRecipes Epic 17)

| Concern              | Choice                                                      | Notes                                          |
| -------------------- | ----------------------------------------------------------- | ---------------------------------------------- |
| Language             | Swift 6.2                                                   | async/await concurrency. Ships with Xcode 26.2 |
| UI framework         | SwiftUI                                                     | iOS 15+ compatible                             |
| State management     | SwiftUI Native (@Observable, @State, @StateObject)          | Modern Apple approach                          |
| Networking           | URLSession + async/await                                    | Native, no third-party                         |
| Local storage        | SwiftData                                                   | Apple's modern persistence; offline cache      |
| Sign-in              | Sign-In with Apple (native)                                 | Google Sign-In via web fallback                |
| Push                 | APNs via Firebase Cloud Messaging (unified backend)         |                                                |
| Billing              | StoreKit 2                                                  |                                                |
| Unit testing         | XCTest (Xcode bundled)                                      | Pure Swift, no UI                              |
| UI-component testing | XCUITest (Xcode bundled)                                    | Single-screen mode                             |
| E2E testing          | Maestro CLI — native macOS install (`brew install maestro`) | Same YAML flows as Android; see §7             |
| Min deployment       | iOS 15.0                                                    |                                                |

The shape of these tables generalizes — every mobile project should have a similar Concern / Choice / Notes table per platform in its `architecture.md` or in the `approved-software-versions.md`.

---

## 7. Mobile testing infrastructure — local everything, native emulators, no Docker

If the web stack lives in Docker, mobile dev tooling is intentionally NOT in Docker. The reasons drive a clear pattern, and they're worth recording so future projects don't re-litigate the decision.

### Why mobile dev tooling stays out of Docker

**Reason 1: iOS simulator cannot run in Docker — at all.** iOS simulator is a macOS-kernel-bound process. Docker on macOS runs Linux containers in a lightweight VM; Linux containers cannot host iOS simulators. iOS testing on a Mac must run native to macOS. This is not a Maestro-specific or project-specific constraint — it's an Apple platform constraint that applies to any iOS test stack (XCUITest, EarlGrey, Appium-iOS, Maestro-iOS).

**Reason 2: Android emulator in Docker is technically possible but heavy and flaky.** Requires KVM hardware acceleration passed through to a Linux container (on Windows: WSL2 + KVM enabled). Container images that bundle this (e.g., `budtmo/docker-android`) run 4–8 GB at runtime, lose GPU acceleration, and are noticeably more flake-prone than native emulators. The standard industry pattern is native Android Studio + native emulator on the developer's host.

**Reason 3: Mobile dev tools have heavyweight native UIs.** Android Studio and Xcode are full IDEs with native UI rendering, plug-in ecosystems, and direct GPU access. Containerizing them adds latency and costs the GPU integration that makes the IDEs usable.

### What lives where

| Tool / service                                                  | Runtime                                                                                         | Why                                                       |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Web stack (Django, Postgres, Redis, MailPit, Next.js — typical) | Docker                                                                                          | Established pattern; consistent service runtime           |
| Android Studio + Android emulator                               | Native (Windows / macOS / Linux host)                                                           | GPU access; standard mobile-dev pattern                   |
| Xcode + iOS simulator                                           | Native macOS                                                                                    | Apple platform constraint; standard mobile-dev pattern    |
| Maestro CLI (Android)                                           | Native install on the Android host (Scoop / PowerShell installer on Windows; Homebrew on macOS) | Single-binary tool; no service to containerize            |
| Maestro CLI (iOS)                                               | Native macOS install (`brew install maestro`)                                                   | Same as above; macOS-side                                 |
| CI runner                                                       | Local `./scripts/ci.sh --story X_Y` on each platform                                            | No GitHub Actions, no Maestro Cloud, no cloud Mac runners |

### Local-CI-only philosophy (no GitHub Actions, no cloud runners)

This pattern recommends running CI locally on each platform, not via cloud runners. Reasons:

- GitHub Actions has a per-account minute quota; high-frequency push patterns blow through it
- Cloud test runners (Maestro Cloud, BrowserStack, Sauce Labs) cost $250+/month per parallel device — not affordable for a solo project
- Local CI gives faster iteration: test runs against the same emulator that's already booted on the dev machine
- Local CI is fully reproducible: same scripts run by future devs with same results

**The `./scripts/ci.sh --story X_Y` pattern** (mirrored from web epics):

1. Boots the platform emulator/simulator if not already running
2. Builds the platform app (`./gradlew assembleDebug` for Android; `xcodebuild` for iOS)
3. Installs the build to the emulator/simulator
4. Runs platform unit-UI tests (Compose Test for Android, XCUITest for iOS), filtered to the story tag
5. Runs Maestro flows tagged `story_X_Y`
6. Reports pass/fail

### Test stack per platform

| Layer                              | Android                                   | iOS                                  |
| ---------------------------------- | ----------------------------------------- | ------------------------------------ |
| Unit (pure Kotlin/Swift, no UI)    | JUnit 4.13.2                              | XCTest (Xcode bundled)               |
| UI-component (single screen, fast) | Compose Test (`androidx.compose.ui.test`) | XCUITest (single-screen mode)        |
| E2E (multi-screen flow)            | **Maestro YAML flows**                    | **Maestro YAML flows (same flows!)** |

**Maestro's cross-platform value:** E2E flows authored once in YAML, run on both Android and iOS. Halves the E2E test maintenance burden across the Android and iOS epics.

### Hardware accommodation

A mobile-multiplatform project typically needs:

- A **Windows / macOS / Linux dev box** with ≥ 16 GB RAM for the host alone after Docker allocation, plus enough headroom for Android Studio + Android emulator + Maestro CLI
- A **Mac** (Mac mini, MacBook, or iMac — Apple-Silicon strongly recommended) with ≥ 16 GB RAM for Xcode + iOS simulator + Maestro CLI for the iOS epic
- A **physical iPhone** (or two, if testing across iPhone sizes) for the iPhone-gated polish tasks — not needed during simulator-driven development, but required before App Store submission

_Example resourcing (PawprintRecipes, 2026-05-05):_

- Windows 11 laptop, 32 GB RAM (16 GB Docker allocation, 16 GB host) — runs web stack in Docker + Android Studio + Android emulator + Maestro CLI
- Mac mini M4, 24 GB RAM — runs Xcode + iOS simulator + Maestro CLI for the iOS epic
- Physical iPhone — pending; iPhone-gated tasks flagged conditional in the iOS Polish story demo

This setup keeps the Docker allocation untouched for the web stack; mobile dev tooling lives in the host RAM on each machine. Comfortable headroom on both.

### Reversibility

The Maestro choice is reversible per-epic. If at any point Maestro install or operation hits a problem on the target host, fallback paths:

- **Android fallback:** Use Espresso (Google's official UI testing framework) for E2E. Adds ~20% E2E test code maintenance for the Android epic, but uses tooling already bundled with Android Studio.
- **iOS fallback:** Use XCUITest for both unit-UI and E2E layers. Adds ~30% E2E test code for the iOS epic vs. cross-platform Maestro flows.

No architecture rewrite needed for either fallback. Story X.1 spike documents the install path that worked; if it doesn't work, the spike documents the fallback path.

---

## 8. The iOS epic should lean on the Android epic patterns — don't duplicate

The iOS epic ships _after_ the Android epic is built and validated. Most of the patterns and conventions are already established. iOS story bodies should:

- Cite Android patterns explicitly: _"Per Story 16.4 mobile home pattern, but using SwiftUI instead of Compose; same `/api/v1/home/` consumption."_
- Innovate only where iOS materially differs:
  - Sign-In with Apple native instead of Google Sign-In native
  - APNs instead of FCM
  - StoreKit 2 instead of Google Play Billing
  - SwiftUI patterns instead of Compose patterns
  - Apple App Store Review Guideline 4.2 polish (extra first-launch demo screen)

**Estimated relative size:** the iOS epic should be ~60–75% the size of the Android epic (e.g., if the Android epic is 14–15 stories, the iOS epic is 9–11 stories). The compression comes from referencing rather than redefining patterns.

**Hardware availability for the iOS epic:** a Mac (Mac mini, MacBook, or iMac — Apple-Silicon recommended) covers approximately 90% of iOS implementation via Xcode + iOS simulator. The remaining ~10% requires a physical iPhone for camera testing in real lighting, real GPS for location-sensitive flows, push notification delivery in real conditions, performance characterization (mobile cold-start NFRs), and App Store Review's physical-device verification expectation before submission.

**iOS implementation can proceed on the Mac up to App Store submission.** iPhone-gated tasks slot into the polish story (X.M) demo steps as conditional verifications — they don't gate the epic's core implementation, only the final pre-submission step.

**Mac onboarding pass for the operator (Story X.1 spike sub-deliverable):** if the operator has the Mac but isn't yet Mac-fluent, Story X.1 spike includes a Mac onboarding section as a sub-deliverable of the conventions doc:

- Initial macOS settings (Trackpad, Finder, security & privacy, network, iCloud)
- Homebrew install (`/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`)
- Xcode install (Mac App Store, ~10–15 GB download — pinned version per `approved-software-versions.md`)
- Xcode command-line tools (`xcode-select --install`)
- Maestro install (`brew install maestro`)
- Apple Developer Program enrollment ($99/year, required for App Store submission and push notification certificates)
- Apple ID + signing certificate setup (the "certificate dance")
- Walking the operator through the first build-and-run on the Mac

This is well-trodden territory — typically a 2–3 hour dedicated session before the iOS epic implementation begins. Skip the section entirely if the operator is already Mac-fluent.

---

## 9. Mobile UX-DR coverage gaps (caveat for mobile-epic authoring)

UX specs are usually written first for web; mobile patterns may not exist yet when the mobile epics are being drafted. The §3.4 upstream-first authoring rule from the [companion epic-writing guide](how-to-write-epics.md) requires same-session UX spec additions for any net-new mobile pattern.

_Example coverage state (PawprintRecipes UX spec at Epic 16/17 drafting time):_

Already covered (UX-DR3–DR13, UX-DR23, UX-DR28):

- Mobile Home — Segments A/B/C/D
- Mobile Navigation Structure
- Action Tile Design
- Smart Context Card Design
- Loading States (Home)
- Accessibility (Home)
- Segment Transition Logic
- Cook Mode at interaction-pattern + defining-experience levels

Likely gaps surfaced during epic drafting (each needed a same-session UX spec addition):

- Mobile login / register / OAuth screens
- Mobile pet onboarding (vs. web onboarding step-1/-2)
- Mobile recipe detail layout (single-column, scroll-driven)
- Mobile feedback flow (drawer? bottom sheet?)
- Mobile DNA upload + camera capture flow
- Mobile billing / subscription screens
- Mobile alert / notification list
- Mobile Settings / About
- First-launch onboarding carousel (the marketing-site replacement)

**Recommended discipline:** Story 16.1 spike (or equivalent first-mobile-epic spike) includes a UX-DR gap audit — list every screen the epic plans to ship and whether a UX-DR exists for it. For each gap, the spike either (a) flags it for the UX specialist to write, or (b) declares "mobile reuses UX-DR<N> with these mobile-specific deltas." Per the companion guide §3.4, the UX-DR additions land BEFORE the story bodies that reference them.

**The spike does NOT decide UX content** — the UX specialist does (typically the Sally subagent per the companion guide §12). The spike just makes the list of decisions explicit and small enough to fit in one work session, so the epic doesn't stall mid-draft.

---

## 10. Quick checklist for the PM author drafting a mobile epic

- [ ] Did NOT add a story for mobile marketing homepage / SEO / sitemap (those don't translate)
- [ ] Did add a story for store listing (Play Store / App Store) — `[infra]` + `[docs]` tags
- [ ] First-launch experience story exists (lean on Android, with extra screen on iOS for App Store Review Guideline 4.2)
- [ ] Polish story includes the cross-cut to update the web marketing badge URLs
- [ ] All cross-platform FRs are sliced into mobile vertical stories (not one mega "Android parity" story)
- [ ] Mobile-specific FRs each have a story or are folded into a logically-related story
- [ ] Story X.1 spike includes a UX-DR gap audit and lists what the UX specialist needs to write
- [ ] Story X.1 spike documents the Maestro install path for the platform (Scoop / PowerShell installer for Windows-Android, Homebrew for Mac-iOS) — no Docker for mobile dev tools (per §7)
- [ ] Story X.1 spike documents the test stack: native unit framework + Compose Test/XCUITest + Maestro YAML flows
- [ ] Story X.M Polish runs locally via `./scripts/ci.sh --story X_M` against native emulator/simulator — no GitHub Actions, no Cloud Maestro
- [ ] Story X.M Polish includes `./scripts/demo-epic-N.sh` with numbered demo steps that walk a fresh device install end-to-end
- [ ] If iOS epic and operator isn't Mac-fluent (Story 17.1 or equivalent): includes Mac onboarding sub-deliverable (Homebrew, Xcode, Maestro, Apple Developer Program enrollment, signing certificates)
- [ ] If iOS epic: each story body cites the Android equivalent and only innovates where iOS differs
- [ ] iPhone-gated tasks called out in the iOS Polish story demo steps as conditional verifications (not core implementation gates)

---

## 11. Phase-N-to-Phase-N+1 gate (timing precondition for mobile epics)

Mobile epics typically don't begin implementation immediately after the web epics complete. There's a real operational checkpoint between phases — the readiness gate. Future projects with phased delivery should treat this gate as a first-class precondition, not an afterthought.

### What the gate is

A phase gate has four shapes:

1. **Time-based:** minimum elapsed time since prior phase launch
2. **Volume-based:** minimum active users with engagement signals
3. **Quality-based:** target metrics met (success metrics + NFR thresholds)
4. **Authority:** named decision-maker (operator) gives the greenlight

_Example gate (PawprintRecipes — PRD §158):_ "After 3 months with 100+ active users (signed up AND made at least one recipe), evaluate against targets to decide whether to proceed to Phase 2 (Android)."

### Where the gate lives in the EPICS structure

Two homes are valid:

- **Light touch (recommended for solo projects):** Story X.1 spike of the first phase-N epic includes a "Phase-N readiness assumption" sub-deliverable. Captures gate criteria, measurement source, decision authority, fallback path.
- **Heavy treatment (recommended for projects with multiple stakeholders):** Standalone document at `_bmad-output/implementation-artifacts/phase-N-readiness.md` referenced from the first phase-N epic header.

### What the spike sub-deliverable should contain

_Example contents (PawprintRecipes Story 16.1 spike's `_bmad-output/implementation-artifacts/16-1-android-conventions.md`, "Phase-2 readiness assumption" section):_

- **Gate criteria:** 3 months since Phase 1 launch + 100+ active users (per PRD §158 definition) + PRD §6 success metric targets met
- **Measurement source:** Staff dashboard from Story 15.6 (`activeUsers`, `recipesMadeMonth`, `apiErrorRate7d`, `dnaErrorRate7d`) — no new technical work needed; the dashboard already exposes these
- **Decision authority:** operator
- **Decision timing:** Quarterly review starting at Phase 1 launch + 3 months
- **Fallback path if gate fails:** Android epic pauses; Phase 1 iteration work continues (CR-driven feature additions, marketing push, UX polish); revisit gate at next quarterly review
- **Trigger event when gate passes:** Operator greenlights Android epic; web marketing site badges remain on coming-soon page until Android Polish story flips them to the real Play Store URL

The iOS epic's Story 17.1 spike includes the equivalent "Phase-3 readiness assumption" section for the iOS gate.

### Why this matters even for solo projects

A solo operator might think "I'll just decide when the time comes" — and then the time comes, and there's no documented criteria, just gut feel. That's a different failure mode from "no gate at all," but it's still a failure: it lets premature mobile work start before the prior phase has actually validated, blowing through development hours on a foundation the market hasn't confirmed.

The spike sub-deliverable is cheap (a single section in the conventions doc) and forces the operator to articulate the criteria once. If the criteria need to evolve later, they evolve once and propagate forward.

### Why NOT a standalone story for the gate

The gate decision is operator authority, not dev agent work. Adding it as a story would:

- Break the vertical-slice principle (no demoable code)
- Conflate operational decisions with implementation epics
- Suggest the dev agent could "implement" the gate, which it can't

The technical infrastructure that supports the gate (typically a staff dashboard with the relevant metrics) is already built in earlier epics. The gate itself is a human checkpoint that consumes that infrastructure.

### Origin

The four-shape gate model (Time / Volume / Quality / Authority) and the "spike sub-deliverable beats standalone doc for solo projects" recommendation generalize to any phased-delivery project. Distilled from PawprintRecipes Epic 16 scoping (2026-05-05).

---

## Companion documents in this directory

- [`how-to-write-epics.md`](how-to-write-epics.md) — the 13 patterns that apply to ALL epics (web and mobile). Read first.
- [`story-and-epic-writing-guide.md`](story-and-epic-writing-guide.md) — story anatomy spec referenced from the companion guide §2
- [`how-to-number-ux-spec.md`](how-to-number-ux-spec.md) — UX-DR numbering procedure (prerequisite for §9 gap audit)
- [`test-structure-guide.md`](test-structure-guide.md) — story-tag conventions and test layout
- [`ci-script-specification.md`](ci-script-specification.md) — CI script the `./scripts/ci.sh --story X_Y` pattern from §7 hooks into

---

_Distilled from PawprintRecipes Epic 16 (Android) + Epic 17 (iOS) scoping (2026-05-05). 11 sections covering web ↔ mobile mapping, platform discovery differences, store-listing handoff, native stack, no-Docker-for-mobile, iOS-leans-on-Android, UX-DR gaps, and the phase gate. If a future mobile epic (e.g., a tablet variant, a wearable, a foldable form factor) reveals a new platform pattern, append a section here._
