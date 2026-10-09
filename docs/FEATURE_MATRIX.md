# Feature Matrix

Evidence gathered by full code reads plus the project's own `pytest` suite (`cd /home/sm/crjs/job-finder && .venv/bin/python -m pytest -q -rs` → 233 passed, 0 failed, 0 skipped, at commit `9f4b6b3`). No live external-API calls were made. "Complete and Tested" below always means a real unit test exercises the real function (not a mocked stand-in for it), unless noted.

Status values used: **Complete and Tested** · **Implemented, Not Fully Tested** · **Partially Implemented** · **Not Implemented** · **Blocked by Configuration** · **Needs Investigation**.

## A. Job Discovery

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Google Jobs via SerpApi | Implemented, Not Fully Tested | `discovery/serpapi_search.py:26-83`; `tests/test_config_http.py:93-128` (mocked HTTP) | Never exercised against the real SerpApi endpoint | Run `main.py --dry-run --max-calls N` with a real key |
| Fresher/Graduate/Junior/Data Analyst/Data Engineer keyword search | Complete and Tested | `discovery/query_builder.py:4-22`; `tests/test_deduplication.py:51-66` | Keyword list hardcoded to Data Analyst/Engineer unless resume supplies other roles | None required |
| India-based + remote-for-India eligibility | Complete and Tested | `filters.py:196-219`; 48 passing cases in `tests/test_filtering.py` | Regex/heuristic over free text; a WFH job that never mentions India is rejected even if genuinely open | Known heuristic ceiling, not a bug |
| Public job-board API (Greenhouse, Lever, Ashby) | Implemented, Not Fully Tested | `verification/ats_clients.py:34-120`; mocked-HTTP tests only | Field-mapping correctness unverified against live responses | One-off manual smoke test per ATS |
| SmartRecruiters client | Partially Implemented (dead code path) | Client exists `ats_clients.py` + `ats_boards.py`, but `boards.json` has **zero** SmartRecruiters entries | No real coverage today despite working code | Add a board entry or drop the client |
| Workday client | Partially Implemented | `ats_clients.py:108-121,138-149`; 2 boards configured (`boards.json:19-20`) | Undocumented JSON endpoint, gated by `robots.txt`; fragile to silent breakage | Monitor; no public contract exists |
| Jobvite | Not Implemented (fetch) | `ats_clients.py:35-37` raises `ValueError`; URL parsing exists in `ats_verifier.py:70-71` but nothing can fetch/verify postings | Jobvite-hosted jobs can reach "ATS link trusted" but never pass vacancy match → stuck at Needs Review forever | Document as permanent gap |
| ATS board discovery | Partially Implemented | `boards.json`: 19 hardcoded companies (8 GH, 5 Lever, 2 Ashby, 2 Workday, 0 SmartRecruiters) | This is curated polling of a fixed allowlist, not open-ended discovery — by design, to avoid spending SerpApi credits | Label accurately in any user-facing copy |
| HR/recruiter search | Complete and Tested (scope-limited by design) | `discovery/hr_search.py:1-59` | Parses only Google's own result titles for LinkedIn `/in/` URLs; never fetches LinkedIn; profiles explicitly labeled unverified | None — matches stated design |
| Deduplication | Complete and Tested | `storage/deduplication.py:1-53`; 7/7 tests | Keys on requisition ID first, else employer+title+location+URL | None required |
| Company-identity cache | Complete and Tested | `verification/company_resolver.py:45-67` (`CompanyCache`, 30d positive/7d negative TTL), persisted via Sheets/Postgres `read_cache`/`write_cache`, not flat files | `.cache/companies.json` on disk confirmed populated from a real run | None required |
| SerpApi budget/quota tracking | Complete and Tested | `budget.py:1-59`; `tests/test_store_budget.py:13-90` | Live `account()` call (confirmed numbers) untested here; logic itself fully covered | Live-path confirmation needs a real key |
| HTTP retry/backoff/robots.txt/politeness | Complete and Tested | `http_client.py:68-132`; `tests/test_config_http.py:65-92` | Rate limiting (`_polite`) is in-process only, won't coordinate across serverless instances | Acceptable at current scale; flag if moving to concurrent multi-instance execution |

## B. Job Verification

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Classification pipeline (4 statuses: VERIFIED/NEEDS_REVIEW/REJECTED/CLOSED) | Complete and Tested | `verification/pipeline.py:45-125`, `models.py:5-9`; 29/29 tests incl. `test_mocked_200_everywhere_without_evidence_is_never_verified` | — | None required |
| Employer/official-site resolution | Implemented, Not Fully Tested | `verification/company_resolver.py` (Google Knowledge Graph + Wikidata P856 fallback) | Small/regional employers without a KG panel always land on Needs Review (README admits this) | Live-test against a real sample of companies |
| Careers-page discovery (must be on official domain) | Implemented, Not Fully Tested | `verification/careers_search.py:50` | JS-rendered (SPA) careers pages return no crawlable links → false negatives | Live smoke-test against real employer sites |
| ATS-board trust (must be official-domain-linked, not just a known ATS URL) | Complete and Tested | `verification/ats_verifier.py:98-107` (explicit anti-"company-name-in-domain" check) | — | None required |
| Exact vacancy match (title/location/requisition ID) | Complete and Tested | `verification/vacancy_matcher.py:45-62` | India-specific city-synonym list hardcoded | Fine for current India-only scope |
| Open/closed/unknown determination | Complete and Tested | `verification/application_status.py:1-34`; explicit `test_http_200_alone_never_means_open` | `CLOSED_MARKERS` regex heuristic for pages without a structured `active` field | Expand marker list as false negatives are observed |
| Apply-URL ownership check | Complete and Tested | `verification/pipeline.py:99-105` | — | None required |
| Eligibility gate (experience/location) inside verification | Complete and Tested | `pipeline.py:110-120` calls `filters.py` | — | None required |
| Verification evidence persistence | Needs Investigation | `logs/verification-2026-10-09.jsonl` confirmed to exist (105KB, real run) | Writer's exact schema (`write_audit` in `main.py`) not read in this audit pass | Confirm schema/retention policy explicitly |
| Retry queue (5 jobs/run, 3 attempts, 12h apart) | Complete and Tested | `storage/store.py:207` (`limit=5, max_attempts=3`), `main.py:299-302` (12h × attempt) | — | None required |

## C. Google Sheets, Postgres & Accounts

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Google Sheets API integration (gspread + service account) | Complete and Tested | `integrations/google_sheets.py:135-184`; 24 tests pass | Error-mapping (403/quota) is unit-tested, not confirmed against a live quota event | None blocking |
| Spreadsheet/worksheet config, header validation | Complete and Tested | `google_sheets.py:34-46,173-184` | Raises and refuses to write on header mismatch — by design | — |
| Job insert/dedup/status-update (Sheets) | Complete and Tested | `google_sheets.py:60-132` | — | — |
| Archive handling (Sheets) | Complete and Tested | `google_sheets.py:233-250` — moves rows, never deletes | — | — |
| Postgres backend (parallel storage implementation) | Complete and Tested | `storage/pg.py`; `storage/backend.py` switches on `STORAGE_BACKEND`/`DATABASE_URL` | — | — |
| Postgres row-level security | Complete and Tested | Migrations `0002` (FORCE RLS + policy), `0003` (restricted non-bypassing `app_rls` role); `storage/pg.py:59-75` | Depends on migration 0003 having applied with sufficient DB privilege | Confirm `/api/health` surfaces `rls_status()` when it hasn't (see Needs Investigation in `KNOWN_ISSUES.md`) |
| Password hashing & lockout | Complete and Tested | scrypt + salt, `accounts.py:29-45`; 5-fail/15-min lockout stored in DB, `accounts.py:130-138` | Lockout is per-account, not per-IP (not claimed to be) | — |
| Session tokens (HMAC, 12h expiry, sign-out-everywhere) | Complete and Tested | `accounts.py:70-88,158-169` | `SESSION_SECRET` must be ≥32 chars or token functions fail closed (good) | — |
| Username sign-in | Complete and Tested | `accounts.py:48-52,92-119`; `tests/test_postgres.py::test_username_login_and_access_requests` | Landed mid-audit in commit `9f4b6b3` | — |
| Admin API-key sharing (request/approve/deny/revoke) | Complete and Tested | `access.py` (new), `routes/access.py`; same test as above | — | — |
| Per-user secret encryption (SerpApi/Groq keys) | Complete and Tested | `user_secrets.py` — Fernet via `SECRETS_KEY`, only a 4-char hint ever returned | `InvalidToken` on key rotation handled as an actionable error, not a crash | — |
| Account deletion cascade | Complete and Tested | `accounts.py:172-178` + `onDelete: Cascade` on every Prisma model, DB-enforced | — | — |
| Per-user Sheets tab mirroring (multi-user → Sheets) | Complete and Tested | `sheet_mirror.py`; 4/4 tests; one-way, never reads back | Best-effort — a Sheets outage is caught/logged and never blocks account creation or search (deliberate trade-off) | — |

## D. Dashboard and API

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Job search & filtering ("default" path) | Implemented, Not Fully Tested | `public/app.js:388`, `routes/run.py` POST | Untested against live SerpApi | — |
| Job search "using my resume" | **Partially Implemented — broken** | `routes/run.py:34` defines `_resume_args()` with 0 params; `routes/run.py:72` calls it with 1 → uncaught `TypeError` | Every real request on this path 500s today; the only test that touches it monkeypatches the function, hiding the bug | Fix signature; add a test on the real function |
| Verified-apply button | Complete and Tested | `routes/jobs.py:31-39` | — | — |
| Status actions / undo | Complete and Tested | `routes/application.py`; `tests/test_lifecycle.py` | — | — |
| Archive / clear | Complete and Tested | `routes/action.py`, `routes/application.py` — never deletes | — | — |
| Dashboard stats / priority labels | Implemented, Not Fully Tested | `public/app.js:323-342`, `priority.py` via `routes/jobs.py:89` | No browser/UI test harness | Manual/E2E check |
| Dark mode / responsive layout | Complete and Tested (by inspection) | `public/app.css:9,14`; one breakpoint at 860px | Single breakpoint, not verified on-device | — |
| Password protection | Complete and Tested | `webapi.authorized`, `accounts.py` scrypt+lockout; confirmed live via dev-server `/api/health` | — | — |
| Resume upload UI/API | Implemented, Not Fully Tested | `routes/resume.py`, `resume_parser.py` | AI extraction currently **Blocked by Configuration** in this `.env` (`LLM_API_KEY` unset) | Set a Groq key to test end-to-end |
| `/api/jobs`, `/api/action`, `/api/application`, `/api/sheet`, `/api/settings`, `/api/serpapi`, `/api/keys`, `/api/ats`, `/api/analytics` | Implemented, Not Fully Tested | Full code read; `test_vercel.py` (37), `test_tailor_auth.py`, `test_resume_library_ats.py`, `test_isolation_guard.py` all pass | None hit real external services in CI | Live smoke test with real credentials |
| `/api/run` (GET=cron, POST=dashboard) | Implemented, Not Fully Tested | `routes/run.py`; `webapi.cron_ok` (Bearer `CRON_SECRET`) | POST "use my resume" path broken (above) | Fix bug, then live test |
| Local dev server | Complete and Tested | Live-booted (`dev_server.py`); `/api/health` returned HTTP 200 with correct config-presence booleans | Health check verifies config/storage presence only, not full page rendering | — |
| Vercel routing (single function, query-param dispatch) + CSP + cron config | Complete and Tested (static config matches README) | `vercel.json`, `api/index.py` | Not verified against an actual Vercel deployment | Deploy once and confirm |

## E. Resume Intelligence

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Resume upload + text extraction | Implemented, Not Fully Tested | `resume_parser.py:20-30` (PDF via pypdf, DOCX via regex); 9/9 tests | Only tested with synthetic files, never a real user resume | Manual test with a real resume |
| File validation (signature/size/pages/corruption) | Complete and Tested | Signature check `:26,28`; 3MB cap `:24`; 10-page cap `:40`; 20MB zip-bomb cap `:52`; encrypted-PDF rejection `:38-39` | DOCX text pulled via regex, not a full XML parser — may miss unusual structures (tables, nested runs) | None urgent |
| Role/skill identification (Groq) | Implemented, Not Fully Tested | `llm.py:18-36,82-103` | Never run against real Groq output | Real-key smoke test |
| Editable profile | Implemented, Not Fully Tested | `clean_profile` (`llm.py:82`) re-validates regardless of source | — | — |
| Resume-to-job matching + score weights (40/20/15/10/10/5, cap 25 if ineligible) | Complete and Tested | `matching.py:15-16,129-147`; 6/6 tests; weights match README exactly | Fixed curated skill dictionary (`matching.py:19-32`), biased toward data/analytics roles | Note as a known limitation outside data roles |
| Match explanations | Complete and Tested | `matching.py:132-147` | — | — |
| Groq/LLM integration | Blocked by Configuration / Needs Investigation (live) | `llm.py:119-149` real call + 401/error handling | **No evidence anywhere of a successful real call** — every test mocks it, `logs/job_finder.log` has no real Groq activity | Run one real end-to-end call with a disposable key |
| Missing-API-key handling | Complete and Tested | `llm.py:122-123,148-149`; `tests/test_resume.py:55-57` | — | — |
| ATS scoring (40/10/15/10/10/10/5) | Complete and Tested | `ats.py:12`; weights match README exactly | Heuristic/regex-based, explicitly documented as an estimate | None urgent |
| Tailoring anti-fabrication checks (no invented numbers; bullets must start from a real bullet; unused keywords flagged "add only if true") | Complete and Tested | All 3 claims verified at `tailor.py` `guard()`: numbers `:52`, bullet-origin `:52`, keyword flag `:60` | Dropped-bullet count surfaced but not which bullet (minor UX gap, not a truthfulness gap) | None urgent |
| Resume version/collection management (max 20, encrypted) | Complete and Tested | `resumes.py:42-43,50` | — | — |

## F. Scheduling and Deployment

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Local systemd scheduler | Implemented, Not Fully Tested; **not currently installed** | `scheduler/setup_schedule.sh` (install/status/run-now/disable/enable/uninstall); `systemctl --user list-timers` shows 0 timers | Script itself warns against double-scheduling with Vercel cron, but nothing enforces mutual exclusion automatically | Run `status`/`run-now` once, deliberately, before relying on it |
| Vercel Cron | Implemented, Not Fully Tested; **not currently deployed** | `vercel.json:8-17` (`30 2 * * *`, `30 14 * * *` UTC = 08:00/20:00 IST); `routes/run.py` enforces `CRON_SECRET` | No `.vercel/` directory found — no evidence of an actual deployment | Deploy, then verify one real cron fire via `/api/health` + logs |
| Run-lock / idempotency | Complete and Tested | `main.py:81-87` (local `fcntl.flock`); `storage/pg.py:194`/`storage/store.py:180` (10-min cross-instance lease) | Local lock is per-machine only (fine for single-host cron+dashboard) | — |
| Duplicate scheduled-run prevention (30-min window) | Complete and Tested | `main.py:161` | — | — |
| Interrupted-run marking | Complete and Tested | `storage/store.py:169-171` | — | — |
| Vercel 240s time budget | Implemented, Not Fully Tested | `webapi.py:153` (`RUN_TIME_LIMIT=240`), `main.py:42,481` saves partial results; platform `maxDuration: 300` in `vercel.json` | Self-imposed 60s safety buffer, not platform-enforced; untested under a real Vercel timeout | Verify under real Vercel execution |

## G. Testing and Security

| Feature | Status | Evidence | Limitations | Next Action |
|---|---|---|---|---|
| Unit/integration test suite | Complete and Tested | 233 tests, 0 failed, 0 skipped; `tests/test_postgres.py` runs against a real throwaway local Postgres | No browser/E2E tests for the dashboard UI | Consider a minimal Playwright/manual-script smoke test |
| Env var validation at startup | Complete and Tested | `config.py:30-60` raises `ConfigError` listing every missing/invalid value; never echoes values | — | — |
| Secret redaction in logs | Complete and Tested | `http_client.py:182-186` `RedactingFilter`, wired into `main.py` logging setup; repo-wide grep found no printed secret value | Redaction is pattern-based | Have the next audit spot-check `redact()`'s regex coverage |
| Rate limiting (searches 3/10min, AI endpoints, login) | Implemented, Not Fully Tested | `routes/run.py:66-67`; `webapi.py` `rate_ok`/login tracking | Explicitly per-instance / best-effort, won't hold across multiple serverless instances | Acceptable at current (Hobby-plan) scale |
| File-upload server-side validation | Complete and Tested | `resume_parser.py` enforces signature/size/page limits server-side (not just client-side) | — | — |
| Secrets never committed to git | Complete and Tested | `git log --all -- .env` empty; `.gitignore` covers `.env`, `credentials.json`, `*.pem`, `*.key`, `*service-account*.json`; no `private_key`/`BEGIN PRIVATE` ever found in any committed JSON | `.env.example` (tracked) hardcodes a real Google Sheet ID as a non-placeholder value | Replace with a placeholder |
| Application lifecycle tracking | Implemented, Not Fully Tested | `applications.py` — full `STAGES` list (superset of the task's proposed lifecycle), `clean_fields`, `apply_change`, `undo`, `history` | No dedicated `test_applications.py` seen; likely covered indirectly by `tests/test_lifecycle.py` | Confirm direct coverage |
| Follow-ups | Implemented, Not Fully Tested | `followups.py` — overdue/today/upcoming for follow-up, assessment, interview, deadline, closing-soon | No dedicated test file confirmed | Confirm direct coverage |
| Priority scoring | Implemented, Not Fully Tested | `priority.py`; `tests/test_priority.py` exists | — | Confirm it exercises all branches |
| Analytics | Implemented, Not Fully Tested | `analytics.py` — by_status/role/location/employment/source/week, match distribution, conversion rates, SerpApi usage | No dedicated `test_analytics.py` seen | Confirm coverage, direct or indirect |
| Evidence of prior live runs | Confirmed | `logs/job_finder.log` (79KB), `logs/verification-2026-10-09.jsonl` (105KB), `.cache/companies.json` (5KB), `.cache/run.lock` — all dated 2026-10-09 | Contents not opened (out of audit scope) | — |
