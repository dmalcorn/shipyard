# How to Handle drf_spectacular Warnings

A reusable target template for Django + DRF + drf_spectacular projects.
Captures the schema-discipline rules that prevent the W001/W002 warning
cascade that hits projects on first contact with `manage.py check
--deploy`. Without these rules, a single epic that adds new auth or
debug endpoints can spike the warning count by 20+ and turn Phase 5
(build verification) into a multi-cycle CI fight.

PawprintRecipes-specific names (`BlacklistCheckingJWTAuthentication`,
`SPECTACULAR_SETTINGS`, `config/settings/dev.py`, `utils/authentication.py`)
appear throughout as concrete examples — substitute your project's
equivalents per the "Adapting to a new project" checklist near the end.

## What it is

drf_spectacular generates the OpenAPI schema from your DRF views.
Its schema generator is strict by design: any view it can't fully
introspect emits a warning. The four most common warning families
in a freshly-onboarded project:

- **`W001`** — "could not resolve authenticator" — fires on every
  endpoint using a custom DRF auth class that has no registered
  `OpenApiAuthenticationExtension`. Scales with API surface area, not
  with the number of auth classes — one missing extension = N
  warnings where N is your endpoint count.
- **`W002`** — "unable to guess serializer" — fires on every
  `@api_view` / APIView without an explicit `request=` in
  `@extend_schema`. Scales with the number of bare views.
- **Enum naming collision** — fires when two serializer fields share
  a literal choice list (e.g. `["ok", "fail"]`) and drf_spectacular
  auto-generates colliding enum class names.
- **Django `security.W*`** — fires on dev-stack settings (`DEBUG=True`,
  short `SECRET_KEY`, no HTTPS) — correct in dev, wrong in prod.
  Strictly Django's, not drf_spectacular's, but they pile in alongside
  the schema warnings in the `manage.py check --deploy` output.

`manage.py check --deploy` is what surfaces all four. CI's Phase 5
build runs that command and fails if anything trips the configured
`--fail-level`. A project with no schema discipline can hit 49+
warnings on a single CI run.

## Why it exists

The PawprintRecipes build hit 49 system-check issues across two CI
cycles before going green: 24 W001s (every endpoint using the custom
JWT class), 12 W002s (debug/test views without `request=`), 1 enum
collision, 6 Django security warnings, plus a handful of strays. Each
required a different fix. Doing it reactively cost hours.

This guide applies the lessons in advance: enable the discipline at
project start so the warnings never accumulate.

## The five rules

### 1. Every `@api_view` / APIView gets an explicit `request=`

`request=None` for views with no body, a serializer for views that
validate input.

```python
# WRONG — emits W002:
@extend_schema(tags=["auth"], responses={200: AccessTokenSerializer})
class CookieTokenRefreshView(APIView):
    def post(self, request: Request) -> Response:
        # reads HttpOnly cookie, returns access token
        ...

# RIGHT — request=None tells drf_spectacular "no body":
@extend_schema(
    tags=["auth"],
    request=None,
    responses={200: AccessTokenSerializer, 401: ErrorEnvelopeSerializer},
)
class CookieTokenRefreshView(APIView):
    def post(self, request: Request) -> Response:
        ...
```

For views with a real request body, declare the serializer:

```python
@extend_schema(
    tags=["auth"],
    request=ChangePasswordRequestSerializer,
    responses={200: ..., 400: ErrorEnvelopeSerializer},
)
class ChangePasswordView(APIView):
    def post(self, request: Request) -> Response:
        ...
```

Letting drf_spectacular fall back to "guess the serializer" is not a
neutral default — it produces W002 noise that compounds across
stories.

### 2. Custom auth classes need a registered `OpenApiAuthenticationExtension`

When introducing or referencing a custom DRF authentication class,
register an extension subclass in the same module:

```python
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework_simplejwt.authentication import JWTAuthentication

class BlacklistCheckingJWTAuthentication(JWTAuthentication):
    """Extends simplejwt with Redis revocation blacklist check."""
    ...

class BlacklistCheckingJWTAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Register the auth class with drf_spectacular so OpenAPI emits
    the correct JWT security scheme on every endpoint."""

    target_class = "utils.authentication.BlacklistCheckingJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT Bearer token. Obtain via POST /api/v1/auth/login/.",
        }
```

The `# type: ignore[no-untyped-call]` is required under strict mypy —
`OpenApiAuthenticationExtension`'s `__init_subclass__` is untyped
upstream.

drf_spectacular auto-registers the extension when the class statement
runs — having it in the same module that defines the auth class
guarantees registration whenever Django imports the module.

### 3. Shared literal choice sets need `ENUM_NAME_OVERRIDES`

When two serializer fields independently declare the same `choices=`
list, drf_spectacular auto-generates colliding enum class names
(`StatusEnum` for one, then `Status1Enum` or similar for the other,
with a warning). Add a canonical name:

```python
# config/settings/base.py
SPECTACULAR_SETTINGS = {
    ...
    "ENUM_NAME_OVERRIDES": {
        "StatusValueEnum": ["ok", "fail"],
    },
}
```

Both fields now resolve to the same `StatusValueEnum` in the schema.
Add an override every time you discover a new collision; they're
silent until you go looking.

### 4. Browser-flow and DEBUG-only endpoints get `exclude=True`

Some endpoints don't belong in the public OpenAPI schema:

- **OAuth flows** that return `HttpResponseRedirect` (302) — they're
  invoked by browser navigation, not by JSON API consumers. SDK
  generators have no use for them.
- **DEBUG-only test endpoints** (registered only when `DEBUG=True`)
  — test infrastructure, not production API.

```python
@extend_schema(
    tags=["auth-oauth"],
    summary="Initiate Google Sign-In",
    request=None,
    exclude=True,  # browser-flow redirect, not a JSON API endpoint
)
class GoogleOAuthStartView(APIView):
    ...

@extend_schema(
    tags=["debug"],
    summary="Test: send seed smoke-test email",
    request=None,
    responses={200: None},
    exclude=True,  # DEBUG-only, not part of public API schema
)
@api_view(["POST"])
def seed_email(request):
    ...
```

`exclude=True` is cleaner than declaring `request=None` plus
`responses={}` shapes that don't really apply — and it removes the
endpoints from API docs entirely, which is what you want for both
categories.

### 5. Dev-only Django security warnings go in `SILENCED_SYSTEM_CHECKS` in `dev.py`

Six Django security warnings fire on intentional dev-stack choices:

| Warning | Triggered by |
|---|---|
| `security.W004` | `SECURE_HSTS_SECONDS` not set |
| `security.W008` | `SECURE_SSL_REDIRECT` not True |
| `security.W009` | `SECRET_KEY` short or starts with `django-insecure-` |
| `security.W012` | `SESSION_COOKIE_SECURE` not True |
| `security.W016` | `CSRF_COOKIE_SECURE` not True |
| `security.W018` | `DEBUG=True` |

These are correct for dev, wrong for prod. Silence them **only in
`config/settings/dev.py`**, not in `base.py`:

```python
# config/settings/dev.py
from .base import *  # noqa: F401, F403

SILENCED_SYSTEM_CHECKS = [
    "security.W004",
    "security.W008",
    "security.W009",
    "security.W012",
    "security.W016",
    "security.W018",
]
```

This way production (which uses `prod.py`, not `dev.py`) still sees
the warnings if they regress. Don't silence `drf_spectacular.W001` or
`W002` globally as a shortcut — fix those at the source per rules 1–2.

## Verification

After enabling the rules, `manage.py check --deploy` should report:

```
System check identified no issues (6 silenced).
```

The 6 silenced are the security.W*. Any other count means a rule was
missed — re-run with `--fail-level WARNING` to see the full list.

Run from the dev container to match what CI sees:

```bash
docker compose -f docker/docker-compose.dev.yml exec -T <backend-service> \
    python manage.py check --deploy
```

## What this guide does NOT cover

- **Per-method schema decoration on mixed-method APIViews** (e.g. a
  view with both `get()` and `patch()` methods that have different
  request bodies) — use `@extend_schema_view(get=..., patch=...)`
  rather than a class-level `@extend_schema`. Out of scope for the
  initial-cleanup rules; needed when you actually have such a view.
- **Polymorphic responses** (different response shapes per status
  code that need separate serializers per code) — supported by
  drf_spectacular, but project-specific.
- **Versioned APIs** (e.g. `/api/v1/...` vs `/api/v2/...`) — each
  needs its own `SpectacularAPIView` registration. Out of scope here.

If you hit any of these, the drf_spectacular docs at
<https://drf-spectacular.readthedocs.io/> are the source of truth.

## Adapting to a new project

| PawprintRecipes value | Replace with |
|---|---|
| `BlacklistCheckingJWTAuthentication` | Your custom DRF auth class name |
| `utils.authentication.<class>` (in `target_class`) | The dotted path of your auth class |
| `name = "jwtAuth"` | A short identifier for the OpenAPI security scheme |
| `config/settings/base.py` | Wherever your project keeps settings (some use `<project>/settings.py`) |
| `config/settings/dev.py` | Your dev-settings file |
| `docker/docker-compose.dev.yml` | Your dev compose file path |
| `<backend-service>` | Your backend service name in the dev compose |

**If your project doesn't use a custom auth class** (default DRF
`SessionAuthentication` / `TokenAuthentication` only), skip rule 2 —
drf_spectacular knows about the built-ins.

**If your project doesn't have OAuth flows or DEBUG-only test
endpoints**, skip rule 4. Add `exclude=True` later when you do.

**If your dev settings inherit production-style security (e.g.
`DEBUG=False` in dev for some reason)**, audit which `security.W*`
warnings actually fire and silence only those — don't blanket-silence
the whole list.

## Cross-references

- Lessons learned 010 in PawprintRecipes captures the original
  incident this guide distills.
- `coding-standards-backend.md` §8d (in each Django target's
  `_bmad-output/planning-artifacts/`) holds the project-internal
  version of the same five rules.
- `BlacklistCheckingJWTAuthenticationScheme` in
  `backend/utils/authentication.py` is the canonical worked example
  of rule 2.
