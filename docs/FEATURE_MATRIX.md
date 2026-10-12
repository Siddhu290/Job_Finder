# Feature Matrix

**Audit date:** 2026-10-12 · **Commit:** `4cedc3b`, plus uncommitted source-priority work (not deployed) · **Tests:** 278 passed, 0 failed, 0 skipped

Rows marked *(new)* describe code that is not deployed, so its "Live" column is "no" until it is.

## What the four columns mean

- **Code:** the implementation exists and was read.
- **Tests:** automated tests exercise the real logic. External HTTP is always mocked: `tests/conftest.py` blocks non-local sockets and scrubs real credentials. Postgres tests run against a throwaway local Postgres, not a mock.
- **Live:** production evidence exists, from read-only aggregate queries on Neon or Vercel logs supplied by the owner.
- **Production-ready:** the feature works live, its failures are visible, and nothing known blocks daily use.

A feature can pass tests and still fail live. N1 in KNOWN_ISSUES is an example.

## Status labels

| Label | Meaning |
|---|---|
| **Verified** | Complete and verified (code, tests and live evidence) |
| **Unit-tested** | Implemented and unit-tested, but not live-tested |
| **Weakly tested** | Implemented but not adequately tested |
| **Partial** | Partially implemented |
| **Broken** | Broken |
| **Blocked** | Blocked by configuration |
| **Not implemented** | Not implemented |
| **Investigate** | Needs investigation |

## A. Job discovery

| Feature | Code | Tests | Live | Status | Evidence | Remaining work |
|---|---|---|---|---|---|---|
| Google Jobs via SerpApi | yes | mocked | yes | **Verified** | live: 10 runs, 178 searches, 44 candidates in one run | None |
| Parallel discovery within the time cap | yes | yes | yes (1 run) | **Verified** | `4cedc3b`; `tests/test_run_route.py`; live: 30 calls in about 3 min | Observe more runs (N6) |
| Fresher / junior / role queries; custom and resume roles | yes | yes | yes | **Verified** | `discovery/query_builder.py`; live: 6 resume roles used | None |
| India and WFH-for-India filters, location chips, work mode | yes | yes (48 cases) | yes | **Verified** | `filters.py`; live: Pune / Bengaluru / Nashik searches | Heuristic ceiling |
| Age filter | yes | yes | yes | **Verified** | live: 8 Rejected for age | None |
| Public ATS boards (Greenhouse, Lever, Ashby, Workday) | yes | mocked | unknown | **Unit-tested** | `boards.json`: 19 boards | Confirm live board fetches in the Vercel logs |
| SmartRecruiters | yes (with pagination) | mocked | no | **Partial** | 0 curated boards; can be discovered from careers pages *(new)* | Add a board |
| *(new)* Source-priority provider registry (configurable order, round-robin paid budget, bounded pool, per-provider errors) | yes | yes | no | **Unit-tested** | `main.plan_tasks` / `discover`; `tests/test_sources.py` | Observe live |
| *(new)* Company career-page discovery (official domain → careers page → linked ATS boards / JobPosting markup; cached) | yes | yes | no | **Unit-tested** | `discovery/company_pages.py`; cache, expiry, pagination, off-domain, closed tests | Live yield unknown |
| *(new)* LinkedIn via Google search (no LinkedIn fetch) | yes | yes | no | **Unit-tested** | `discovery/platform_search.py` | Google title formats may change; parse rate unknown |
| *(new)* Naukri via Google search (no Naukri fetch) | yes | yes | no | **Unit-tested** | same | same |
| *(new)* Source labels, tiers (`SOURCE_TIERS`), canonical URLs, source IDs, provenance in `checks.sources` | yes | yes | no | **Unit-tested** | `discovery/sources.py` | — |
| *(new)* Cross-source dedupe (official URL canonical; different requisitions kept apart) | yes | yes | no | **Unit-tested** | `storage/deduplication.py` | — |
| Jobvite | detect only | yes | n/a | **Not implemented** (fetch) | `ats_clients.py:31`; now reported as "unsupported", not as an error *(new)* | Permanent gap |
| HR / LinkedIn profile links (Google results only) | yes | yes | unknown | **Unit-tested** | `discovery/hr_search.py` | Check in the UI |
| Deduplication | yes | yes | yes | **Verified** | live: 44 unique out of 44 | None |
| Budget per run and per month, per key | yes | yes | yes | **Verified**, with a skew | live: usage rows per key fingerprint | 16 phantom calls (N5) |
| Retry queue for pending verification | yes | yes | yes | **Verified** | `1edf5d0`; live: Needs Review saved, not discarded | Robots refusals are retried pointlessly (N4) |

## B. Verification

| Gate | Code | Tests | Live | Status | Evidence | Remaining work |
|---|---|---|---|---|---|---|
| Employer identity / official website (Knowledge Graph or Wikidata) | yes | yes | yes | **Partial** in effect | live: 47 of 85 stop here | Fallback for SMEs (FUTURE_SCOPE P1-3) |
| Careers page on the official domain | yes | yes | yes | **Unit-tested**; works live but rarely leads further | live: 15 "careers page found, no verifiable vacancy" | JS-rendered pages |
| ATS board linked by the employer | yes | yes | no live pass | **Unit-tested** | `ats_verifier.py` | None |
| Exact vacancy / requisition ID | yes | yes | 1 live miss | **Unit-tested** | `vacancy_matcher.py` | None |
| Location and experience eligibility | yes | yes | yes | **Verified** | live Rejected records | None |
| Open / closed (HTTP 200 is never enough) | yes | yes | no live pass | **Unit-tested** | `application_status.py`; `test_http_200_alone_never_means_open` | None |
| Official apply URL matches the vacancy | yes | yes | no live pass | **Unit-tested** | `pipeline.py` | None |
| Evidence stored for later review | yes | yes | yes | **Verified** (Postgres) | live: 85 records with `checks` JSON; the JSONL file is ephemeral on Vercel (N13) | Show the evidence in the UI |
| Uncertain → Needs Review with a reason | yes | yes | yes | **Verified** | live grouped reasons | PermissionError wording (N4) |
| **End to end: a job reaches Verified live** | yes | yes | **0 of 85** | **Investigate** | KNOWN_ISSUES N3 | FUTURE_SCOPE P1-3 |

## C. Dashboard and application lifecycle

| Feature | Code | Tests | Live | Status | Evidence | Remaining work |
|---|---|---|---|---|---|---|
| Sign-in (email or username) and create-account pages | yes | yes | yes | **Verified** | live: `/api/register` and `/api/login` 200 | None |
| Dashboard stats | yes | weak | yes (renders) | **Weakly tested** | screenshots | No UI tests |
| Find Jobs: role and location chips, mode, age, preview, resume roles | yes | yes (API) | yes | **Verified** | live screenshots and runs | None |
| Search history table | yes | yes | yes | **Verified** | screenshots | Mixed run-ID formats (N15) |
| Job cards: match %, skills needed, missing skills, responsibilities, Apply | yes | yes | yes | **Verified** | screenshot 2026-10-09 | None |
| *(new)* Source chips with links, "Official company posting" only from evidence, "Supplementary source", Employer website, Original posting, last checked | yes | API tested (`source_info`) | no | **Unit-tested** | `routes/jobs.py`, `public/app.js` | No browser test |
| *(new)* Source filter and "Official postings first" toggle | yes | no (UI) | no | **Weakly tested** | `public/app.js` | Manual check |
| Saved / Applied / Not interested / no repeats / clear | yes | yes | partly | **Unit-tested** | 23 live history rows; 0 applications | Use live once |
| Applications stages, notes, undo | yes | yes (`test_lifecycle.py`) | no | **Unit-tested** | 0 live rows | None |
| Follow-ups | yes | yes | no | **Unit-tested** | `test_followup_buckets_and_no_duplicates` | None |
| Analytics | yes | yes | renders | **Unit-tested** | `test_analytics_from_stored_data_only` | None |
| Settings: own SerpApi and Groq keys with links | yes | yes | yes | **Verified** | live: 1 user with saved keys | None |
| Request access to the admin's keys; approve / deny / revoke | yes | yes | yes | **Verified** | live: 2 approved users | None |
| Archive and restore | yes | yes | unknown | **Unit-tested** | `test_application_api_archive_restore` | None |
| Admin view | yes | yes | yes | **Verified** | approvals done live | None |
| Backend errors shown clearly | yes | yes | yes | **Verified** | `14fbb18`: JSON errors instead of a bare 500 | None |
| Mobile and keyboard-only use | partial | no | unknown | **Investigate** | one 860px breakpoint | Manual check |

## D. Resume and AI

| Feature | Code | Tests | Live | Status | Evidence | Remaining work |
|---|---|---|---|---|---|---|
| PDF and DOCX upload with validation | yes | yes | yes | **Verified** | live: 4 stored resume versions | DOCX tables (P3) |
| Groq role and skill extraction | yes | mocked | yes | **Verified** | live: 3 AI profiles; model fallback `c989c30` | Review output quality |
| Edit and save the profile | yes | yes | unknown | **Unit-tested** | `profiles.update` | None |
| Resume-to-job match score and explanation | yes | yes | yes | **Verified** | live job cards show match % and missing skills | None |
| ATS score against a JD, with suggestions | yes | yes | yes | **Verified** | live: `/api/ats` 200 | None |
| Tailoring with anti-fabrication guards | yes | yes (guards) | yes | **Verified** (endpoint) | live: `/api/tailor` 200 | Review whether the output is truthful |
| Named resume collection (max 20, encrypted) | yes | yes | yes | **Verified** | live `_resumes` and `_resume_*` docs | None |
| Export / print a tailored resume | yes | yes | unknown | **Unit-tested** | README, `resumes.py` | Manual check |
| Auto-tailor on Apply (future scope) | no | no | no | **Not implemented** | README future scope | FUTURE_SCOPE P3 |

## E. Storage and security

| Feature | Code | Tests | Live | Status | Evidence | Remaining work |
|---|---|---|---|---|---|---|
| Active backend | Postgres (Neon) | — | yes | **Verified** | `.env` and Vercel set DATABASE_URL; live data | None |
| Row-level security (FORCE plus restricted `app_rls` role) | yes | yes (real Postgres) | yes | **Verified** | `rls_status()` returns `enforced` live; migrations 0001-0004 applied | Health check depth (N12) |
| Passwords, lockout, sessions, sign out everywhere | yes | yes | yes | **Verified** | live logins | None |
| Per-user key encryption (Fernet) | yes | yes | yes | **Verified** | live `_secrets` doc | None |
| Per-user Google Sheet tab | yes | yes | unknown | **Unit-tested** | `sheet_mirror.py` | Check the sheet |
| Health check reports storage and RLS | yes | yes | yes | **Verified** | `routes/health.py:29-30` | N12 |
| Google Sheets single-user mode | yes | yes | not in use | **Unit-tested** | — | None |

## F. Scheduling and deployment

| Feature | Code | Tests | Live | Status | Evidence | Remaining work |
|---|---|---|---|---|---|---|
| Vercel deployment (one function plus rewrites, CSP) | yes | yes | yes | **Verified** | owner's Vercel logs | None |
| Vercel cron, multi-user | `cron_all_users` implemented *(new)* | yes: authorised path, fairness, time slices, real-Postgres isolation | 0 cron runs (old code live) | **Unit-tested**, not deployed | `tests/test_sources.py`, `tests/test_postgres.py` | Deploy; set `CRON_SECRET`; trigger once |
| Local systemd timer | yes | n/a | not installed | **Blocked** (owner's choice) | no timers | Use Vercel cron *or* systemd, not both |
| Run lock, interrupted-run marking | yes | yes | yes | **Verified** | live: an `interrupted` run was marked | None |
| Run time within Vercel's 300 s | yes | yes | yes (about 3 min) | **Verified** (1 run) | live | N6 |
| Logs and monitoring | Vercel logs | n/a | yes | **Partial** | no alerts | FUTURE_SCOPE P2 |
