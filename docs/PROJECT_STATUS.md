# Project Status — Fresher Data Job Finder

**Audit date:** 2026-10-09
**Audited commit:** `9f4b6b3` ("Request access to the admin's API keys...; username sign-in; migration 0004") — the working tree was clean at the end of the audit.
**Method:** full code read of every module in scope, plus the project's own `pytest` suite run locally. No live SerpApi, Groq, Google Sheets, or Postgres calls were made against real credentials; `tests/conftest.py` blocks non-local network and scrubs real-service env vars for every test.

## One-paragraph summary

This is a considerably more mature project than a first glance at the task brief would suggest. It already has a working dual storage backend (Google Sheets for single-user, Neon Postgres with enforced row-level security for multi-user), a genuine multi-stage job-verification pipeline that refuses to call a job "Verified" on HTTP-200-alone, resume parsing + Groq-based profile extraction + ATS scoring + anti-fabrication tailoring, a full application-lifecycle tracker, follow-up reminders, and an analytics module — most of the things the task's "Future Scope" phases ask for already exist in some form. The codebase is honest about its own limits (README §12 "Known limitations" is accurate). The test suite is large (233 tests) and passes cleanly. The most important finding is a single reproducible, UI-reachable bug that crashes a real feature, plus confirmation that the LLM/AI path has never been exercised against a live Groq key.

## Test suite result

```
cd /home/sm/crjs/job-finder && .venv/bin/python -m pytest -q -rs
```
**233 passed, 0 failed, 0 skipped.** `tests/test_postgres.py` (15 tests) spins up a real throwaway local Postgres from `/usr/lib/postgresql/*/bin`, applies the actual Prisma migrations, and runs as a non-superuser role — it is not mocked, and it was not skipped on this machine.

(Mid-audit, a real commit — `9f4b6b3` — landed on `main`, fixing a transient 1-test failure the audit first observed; see [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) for the before/after.)

## What's implemented (verified, by subsystem)

| Subsystem | Verified status |
|---|---|
| Job discovery (SerpApi Google Jobs, curated ATS board polling, HR search, dedup, budget tracking, retry/backoff) | Working, well-tested (89/89 relevant tests). ATS coverage is a static 19-company allowlist, not open-ended discovery. |
| Job verification (8-gate pipeline: employer → official site → careers page → ATS link trust → exact vacancy → open/closed → URL ownership → eligibility) | Working, well-tested (29/29). Explicitly never treats a reachable URL as proof. Jobvite postings can never reach `Verified` (no fetch client exists for it). |
| Storage (Google Sheets + Postgres w/ RLS, accounts, per-user secret encryption, Sheets mirroring) | Working, well-tested (44/44 in this area; RLS enforced at the Postgres policy level with a non-bypassing DB role, not just app code). |
| Dashboard & API (18 routes, auth, rate limiting, CSP/cron config) | Mostly working — **one real bug** (below) crashes "search using my resume." |
| Resume intelligence (parsing, matching weights, ATS scoring, Groq tailoring with anti-fabrication checks) | Logic fully implemented and unit-tested (36/36) against the exact numeric claims in the README. **Never run against a real Groq API key.** |
| Application tracking, follow-ups, priority scoring, analytics | Already implemented, not just planned — `applications.py`'s stage list is a *superset* of the task brief's proposed lifecycle. Test coverage for these specific modules needs a second pass (see [`FEATURE_MATRIX.md`](FEATURE_MATRIX.md)). |
| Scheduling | Both the local systemd timer and Vercel cron are implemented but **neither is currently active** on this machine/deployment. |
| Security hygiene | No secret has ever been logged, printed, or committed to git in this repo's history. `.env` was never committed. One minor hygiene issue: `.env.example` (tracked in git) hardcodes a real-looking Google Sheet ID instead of a placeholder. |

## Confirmed working through tests

Discovery, verification, storage/accounts, matching/ATS/tailoring anti-fabrication logic, run-lock/idempotency, duplicate-run prevention, env validation, secret redaction — all have passing, non-trivial unit tests that exercise real logic (not just imports).

## Implemented but still unverified end-to-end

- **Groq/LLM integration** — every test mocks the HTTP call; no evidence anywhere (logs, fixtures, code) of a real Groq API call ever having succeeded.
- **Live SerpApi / ATS-board fetches** — unit-tested with mocked HTTP only; `logs/` and `.cache/` show the app *has* been run live at least once today (2026-10-09), but that run's actual success/failure detail wasn't inspected (out of scope — contents weren't opened).
- **Vercel deployment** — `vercel.json` and the routing/CSP/cron config are correct by inspection; there is no evidence the app is currently deployed (no `.vercel/` directory found).

## Blocked by configuration (in this exact checkout, right now)

This `.env` is currently configured for **single-user Google Sheets mode**: `SERPAPI_KEY`, `GOOGLE_SHEET_ID`, `DASHBOARD_PASSWORD`, and `SECRETS_KEY` are set; `DATABASE_URL`, `SESSION_SECRET`, and `LLM_API_KEY` are **not**. That means, right now: multi-user/Postgres mode is inactive, and all Groq-backed AI features (resume extraction, tailoring suggestions) will fail with a clear, handled error rather than a crash (`llm.py` raises `LLMError` with a signup link — confirmed in code).

## What remains unfinished

- The `_resume_args` crash (below) needs a one-line fix.
- A real end-to-end Groq smoke test (one real API key, one real resume) has never been run.
- Neither scheduler has been activated; the project's own tooling explicitly warns against running both at once.
- SmartRecruiters has a working client but zero configured boards — dead code path today.
- Test coverage for `applications.py`, `followups.py`, `analytics.py` needs explicit confirmation (likely covered indirectly by `test_lifecycle.py`, but no dedicated `test_applications.py`/`test_analytics.py` file exists).

## Most important known issues

1. **P0 bug:** `routes/run.py` crashes with an uncaught `TypeError` whenever a user searches "using my resume" (`_resume_args()` is defined with 0 parameters but called with 1). The existing test monkeypatches around the real function, masking it.
2. **Jobvite-hosted jobs can never be verified** — a permanent gap, not a bug, but worth stating plainly so "Needs Review" isn't mistaken for a bug.
3. **LLM/AI path is untested in the real world.**
4. `.env.example` leaks a real Sheet ID into git history as a non-placeholder value.

Full detail: [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).

## Top 5 next actions

1. Fix `_resume_args()`'s signature in `routes/run.py` (trivial, one line) and add a test that calls the real function instead of a monkeypatched stand-in.
2. Run one supervised, real Groq API call (disposable key, one real resume) to confirm the LLM path actually works end-to-end before depending on it.
3. Decide and activate exactly one scheduler (local systemd *or* Vercel cron, never both, per the project's own existing guard) before relying on automated runs.
4. Replace the real `GOOGLE_SHEET_ID` in `.env.example` with a placeholder.
5. Add direct unit tests for `applications.py`, `followups.py`, and `analytics.py` if none exist beyond indirect coverage via `test_lifecycle.py`.

## Readiness assessment

| Use case | Ready? | Why |
|---|---|---|
| **Local use** | **Yes, with one caveat** | Dev server boots, `/api/health` responds correctly, core search/verify/dashboard flow is tested — but avoid the "search using my resume" checkbox until the bug above is fixed. |
| **Daily automation (scheduled runs)** | **Not yet** | The run pipeline itself is solid and idempotent, but no scheduler is currently active, and the LLM path it may depend on (if resume-based search is used) has the open bug and is untested live. Activate one scheduler deliberately, fix the bug first. |
| **Production deployment (Vercel, multi-user)** | **Not yet** | Code and config (CSP, cron, RLS, rate limiting) are all in place and unit-tested, but there is no evidence of an actual deployment, no live Groq/SerpApi smoke test, and `SESSION_SECRET`/`DATABASE_URL` aren't set in the current local `.env` (expected — those are only needed in multi-user mode). Before going to production: run the top-5 actions above, then do one real deploy + one real cron fire + one real multi-user signup, and confirm `/api/health`'s storage/RLS checks pass against the live Neon database. |

## Documentation produced

- `docs/PROJECT_STATUS.md` (this file)
- `docs/FEATURE_MATRIX.md`
- `docs/ARCHITECTURE.md`
- `docs/FUTURE_SCOPE.md`
- `docs/TESTING_AND_DEPLOYMENT.md`
- `docs/KNOWN_ISSUES.md`
