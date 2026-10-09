# Known Issues

Ordered by severity. Each item states how it was confirmed (code inspection, reproduction, or test evidence) so nothing here is a guess.

## P0 — Reproducible bug, user-facing crash

### `routes/run.py` crashes on "search using my resume"

- **What:** `_resume_args()` is defined with zero parameters (`routes/run.py:34`), but is called with one positional argument at `routes/run.py:72`. Every real request that checks the "use my resume" option in a search raises an uncaught `TypeError`.
- **Reproduced directly:**
  ```
  $ .venv/bin/python3 -c "import routes.run as r; r._resume_args(object())"
  TypeError: _resume_args() takes 0 positional arguments but 1 was given
  ```
- **Why the test suite didn't catch it:** `tests/test_resume.py:121` monkeypatches `run_api._resume_args` with `lambda *a: [...]` before exercising the route, which hides the real function's broken signature. The test suite is green; the feature is broken.
- **Impact:** UI-reachable (wired from `public/app.js:376,382`), not theoretical.
- **Fix:** add the missing parameter to `_resume_args`'s signature (or remove the argument at the call site, whichever matches the intended behavior — needs a one-line look at what the caller is trying to pass). Then replace the monkeypatch-based test with one that calls the real function.

## P0 — Standing credential-hygiene policy (not a new finding, but worth repeating)

The project's own README already states: *"credentials previously pasted into chats should be treated as compromised. Rotate the SerpApi key, the Google service-account key and the dashboard password."* This audit did not identify any specific leaked value (no secret was ever found committed to git, logged, or printed by any code path — see the Security section below), but this is a standing policy worth re-confirming periodically, especially before a production deployment.

## P1 — Untested external integration

### Groq/LLM resume intelligence has never been exercised against a real API key

- **What:** every test that reaches `llm.chat_json` mocks it (`tests/test_resume_library_ats.py:111`, `tests/test_tailor_auth.py:42,94`, `tests/test_resume.py:26-27`). `logs/job_finder.log` (a real run log from 2026-10-09) contains zero real Groq API activity. No fixture contains a real resume sample.
- **Why it matters:** resume profile extraction, ATS AI suggestions, and tailoring drafts all depend on this working correctly against real model output, which can differ from hand-built test JSON in format and edge cases.
- **Current state in this environment:** `LLM_API_KEY` is not set in this `.env`, so the feature currently fails closed with a clear, handled error (`llm.py` raises `LLMError` with a signup link) rather than crashing — that part is correct and tested.
- **Fix:** before relying on this in production, run one supervised end-to-end test with a disposable Groq key and a real resume, and inspect the actual output quality.

## P1 — Test-coverage gaps

- No dedicated test file was found for `applications.py` (`test_applications.py`) or `analytics.py` (`test_analytics.py`). `applications.py` is likely exercised indirectly through `tests/test_lifecycle.py`, but this should be confirmed, not assumed, given both modules are real, non-trivial business logic (stage transitions, conversion-rate math).
- No automated UI/browser test exists for the dashboard. Loading states, empty states, and keyboard accessibility were not exercised by anything automated during this audit.

## P2 — Design/coverage limitations (not bugs)

### Jobvite-hosted jobs can never reach "Verified"

`verification/ats_clients.py:35-37` raises `ValueError` for Jobvite — there is no public API to fetch postings from it, even though `ats_verifier.py:70-71` can *recognize* a Jobvite URL. Any job hosted on Jobvite will permanently sit at `Needs Review`, by design, because the pipeline correctly refuses to call something Verified without evidence. **This is not a bug** — it's the system working correctly with incomplete data — but it should be communicated to users so "Needs Review" on a Jobvite job isn't mistaken for a verification failure.

### SmartRecruiters client exists but is never exercised

`verification/ats_clients.py` has a working SmartRecruiters client, and `ats_boards.py` treats it as a supported board type, but `boards.json` currently has **zero** SmartRecruiters entries. This is dead code in practice until a board is added.

### Workday integration is fragile by necessity

`ats_clients.py:108-121,138-149` uses an **undocumented** Workday JSON endpoint (`/wday/cxs/...`), correctly gated behind a `robots.txt` check. If Workday changes this endpoint or tightens `robots.txt`, Workday coverage silently drops to zero with no alerting — the failure is caught generically in `ats_boards.py:34-36`, not surfaced distinctly.

### Rate limiting and run-locks are per-instance, not distributed

`http_client.py`'s politeness throttle and `webapi.py`'s rate-limit tracking use in-process state. On Vercel this is fine today (effectively one instance per cron slot), but it would not hold up under genuine concurrent multi-instance execution. This is explicitly documented in the README as "best effort," so it's a known, accepted limitation rather than an oversight — flagged here only so it isn't rediscovered as a surprise later.

### `.env.example` commits a real-looking Google Sheet ID

`.env.example` line 17 hardcodes `GOOGLE_SHEET_ID=1oivue0amQNqJQbEzX32UJFieK8rn24NnUpufpt3Lvug` instead of a placeholder, unlike every other field in that file. A Sheet ID alone isn't a credential (Google Sheets access is controlled by ACL/sharing, not by knowing the ID), so this is a hygiene issue, not an active vulnerability — but it reveals which specific spreadsheet is in production use to anyone who reads the public-ish example file. **Recommendation:** replace with a placeholder.

### Postgres RLS failure visibility unconfirmed

`storage/pg.py` exposes `rls_status()`, and the README promises `/api/health` reports RLS health when signed in. This audit could not confirm, with certainty, that `routes/health.py` actually calls `rls_status()` and surfaces a failure if migration `0003` (the restricted role) hasn't been applied with sufficient DB privilege on a given host. Marked **Needs Investigation** — worth a direct check of `routes/health.py` before relying on this signal in a hosted-Postgres production deployment.

### Verification evidence log schema undocumented

`logs/verification-2026-10-09.jsonl` (105KB) exists and is clearly written by a real run, but the exact schema written by `write_audit` (referenced in `main.py`) wasn't read in this audit pass (scope was limited to directory structure, not contents, to avoid exposing any sensitive evidence data). Recommend documenting the schema once, separately.

## P3 — Cosmetic / minor

- Tailoring guard surfaces a count of dropped (fabricated-looking) suggestions but not which specific bullet was dropped — a minor UX gap, not a truthfulness gap (the truthfulness guarantee itself is correctly enforced).
- DOCX text extraction (`resume_parser.py`) uses a regex-based approach rather than a full XML parser — works for simple documents, may miss text in unusual structures (tables, deeply nested runs). No failure observed in testing, but worth knowing as a ceiling.
- Dashboard CSS has a single responsive breakpoint (860px) — not verified on-device across a range of phone/tablet sizes.

## Neither currently active: the two schedulers

Both the local systemd timer (`scheduler/setup_schedule.sh`) and Vercel Cron (`vercel.json`) are fully implemented, but **neither is currently installed/deployed**: `systemctl --user list-timers` shows zero timers on this machine, and no `.vercel/` directory indicates a deployment. This is not a defect — it's the expected state for a project that hasn't been put into daily automated use yet — but it means no scheduled run has ever actually fired in production, only manual/local runs (confirmed via `logs/job_finder.log` and `.cache/companies.json` timestamps from 2026-10-09).

## Security summary (no open findings beyond the above)

- No secret value has ever been logged, printed, or committed to git in this repository's history. `.env` has zero git history. `.gitignore` correctly covers `.env`, `credentials.json`, `*.pem`, `*.key`, `*service-account*.json`.
- A repo-wide search for `private_key`/`BEGIN PRIVATE`/`client_secret` across every JSON ever committed found nothing.
- Password hashing (scrypt), account lockout (DB-persisted), session tokens (HMAC, 12h expiry, revocable), and per-user secret encryption (Fernet) are all implemented correctly and covered by passing tests against a real throwaway Postgres instance.
- `config.py` fails closed on missing/invalid configuration and never logs secret values; `http_client.py` has an active log-redaction filter.
