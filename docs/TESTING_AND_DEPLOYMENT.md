# Testing and Deployment

## Exact test command and result

```bash
cd /home/sm/crjs/job-finder
.venv/bin/python -m pytest -q -rs
```

**Result: 233 passed, 0 failed, 0 skipped** (at commit `9f4b6b3`).

This is a real, non-trivial test suite — not a thin smoke-test layer:

- `tests/test_postgres.py` (15 tests) starts a **real, throwaway local Postgres instance** using local server binaries (`/usr/lib/postgresql/*/bin`), applies the actual Prisma migrations, and connects as a non-superuser `app_rls` role to confirm row-level security actually holds at the database level — not mocked, not skipped on this machine. (If Postgres binaries aren't installed on a given machine, the README states these tests are skipped instead — on this machine they ran for real.)
- `tests/conftest.py` enforces, for every test in the suite: (1) the real `.env` is never loaded, (2) all real-service env vars (`DATABASE_URL`, `SERPAPI_KEY`, `LLM_API_KEY`, `SESSION_SECRET`, `SECRETS_KEY`, etc.) are scrubbed from the environment, and (3) any socket connection to a non-local address raises immediately. This means the entire suite is provably incapable of reaching a real external service, by construction, not by convention.

### Per-subsystem test runs performed during this audit

| Command | Result |
|---|---|
| `pytest -q tests/test_deduplication.py tests/test_filtering.py tests/test_store_budget.py tests/test_config_http.py` | 89 passed |
| `pytest -q tests/test_verification.py` | 29 passed |
| `pytest -q tests/test_postgres.py tests/test_google_sheets.py tests/test_sheet_mirror.py tests/test_isolation_guard.py` | 44 passed |
| `pytest -q tests/test_vercel.py tests/test_main.py tests/test_lifecycle.py tests/test_resume.py` | 37 passed |
| `pytest -q tests/test_tailor_auth.py tests/test_resume_library_ats.py tests/test_isolation_guard.py` | 13 passed |
| `pytest -q tests/test_resume.py tests/test_resume_parser.py tests/test_resume_library_ats.py tests/test_matching.py tests/test_tailor_auth.py` | 36 passed |
| `pytest -q -rs` (full suite, final) | 233 passed, 0 failed, 0 skipped |

### A note on the one failure observed mid-audit

Early in this audit, the full suite showed **231 passed, 1 failed** (`tests/test_postgres.py::test_accounts_password_lockout_and_sessions`, expecting the error string `"Wrong email or password"` but getting `"Wrong email/username or password"`). Mid-audit, you landed commit `9f4b6b3`, which added username-based login and updated both `accounts.py`'s message and the test's expectation together. The failure was real but transient — caused by the test lagging one commit behind in-flight work, not a defect. At final HEAD it is fully resolved (233 passed, 0 failed, one new test added).

### Gaps in test coverage found

- No dedicated `test_applications.py` or `test_analytics.py` was found; `applications.py` is likely covered indirectly via `tests/test_lifecycle.py`, but this should be confirmed explicitly rather than assumed.
- The `routes/run.py` "use my resume" code path has a test (`tests/test_resume.py:121`) that **monkeypatches the broken function it's supposed to test**, so it passes while the real code is broken. This is the single most important finding of the whole audit from a process standpoint: a green test suite did not catch a real, user-facing crash. See `KNOWN_ISSUES.md`.
- No browser/end-to-end UI test exists for the dashboard; loading states, empty states, and accessibility were not exercised by any automated test.

## Environment requirements

Two independent modes, controlled by which env vars are set (see `.env.example`, which documents every variable with no secret values):

### Single-user (Google Sheets) — this repo's current local `.env` is configured this way
Required: `SERPAPI_KEY`, `GOOGLE_SHEET_ID`, `GOOGLE_CREDENTIALS` (or `GOOGLE_CREDENTIALS_JSON` on Vercel), `DASHBOARD_PASSWORD`.
Confirmed present in this `.env` (presence only, via `/api/health` output during this audit): `SERPAPI_KEY=true`, `GOOGLE_SHEET_ID=true`, `DASHBOARD_PASSWORD=true`, `SECRETS_KEY=true`.
Confirmed absent: `DATABASE_URL=false`, `SESSION_SECRET=false`, `LLM_API_KEY=false`.

### Multi-user (Neon Postgres)
Required: `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct, for migrations), `SESSION_SECRET` (≥32 chars), `SECRETS_KEY` (Fernet key). Optional: `ALLOW_SIGNUP`, `INVITE_CODE`.
**Not currently configured in this environment.** Multi-user mode is implemented and tested (via the throwaway-Postgres test suite) but not active here.

### Both modes
`LLM_API_KEY` (Groq) for resume AI features — **not currently set**, so AI resume extraction/tailoring is Blocked by Configuration in this exact checkout, though the underlying code is implemented. `CRON_SECRET` for scheduled runs — status not independently confirmed in this audit pass.

## Deployment readiness

| Aspect | Status |
|---|---|
| Deployment config (`vercel.json`: functions, rewrites, CSP/security headers, cron schedule) | Present and correct by inspection |
| Evidence of an actual live deployment | **None found** — no `.vercel/` directory in this checkout |
| Scheduler currently active | **Neither** — local systemd timer not installed (`systemctl --user list-timers` → 0 timers); Vercel cron defined in code but no deployment to run on |
| Secrets never logged/committed | Confirmed — `.env` never in git history; no secret value found in any committed file; `config.py` never logs values |
| `.env.example` hygiene | One issue — a real-looking `GOOGLE_SHEET_ID` is committed as a non-placeholder value |

## Remaining validation before production use

1. Fix the `_resume_args()` bug (see `KNOWN_ISSUES.md`) and re-test the "search using my resume" path for real.
2. Run one real Groq API call end-to-end (disposable key + one real resume) — currently zero evidence this has ever succeeded.
3. Run one real SerpApi search via `main.py --dry-run --max-calls 5` against a live key, to confirm the live JSON shape still matches what `discovery/serpapi_search.py` expects.
4. Deploy once to Vercel and confirm `/api/health` responds correctly in that environment, including (if multi-user) the Postgres RLS status.
5. Activate exactly one scheduler and confirm one real scheduled run completes and is correctly recorded (not marked "interrupted").
6. Replace `.env.example`'s real Sheet ID with a placeholder.

None of the above were performed in this audit — per the task's explicit instructions not to trigger live searches, modify production data, enable scheduling, or deploy.
