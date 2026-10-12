# Known Issues

**Audit date:** 2026-10-12 · **Commit:** `4cedc3b` (branch `main`, clean working tree) · **Tests:** 238 passed, 0 failed, 0 skipped

Each item says how it was confirmed. Evidence types: **code** (read the source), **test** (pytest result), **live** (production records in Neon Postgres, read-only aggregate queries, or Vercel logs supplied by the owner), **inference** (reasoned, not proven).

The previous audit (2026-10-09, commit `9f4b6b3`) is reviewed item by item in "Previous findings" at the end of this file.

## Update 2026-10-12: source-priority discovery work

These changes are uncommitted on top of `4cedc3b`, **not deployed**, with 263 tests passing. Hands-on test results are in TESTING_AND_DEPLOYMENT.md.

| Item | Status now | Evidence |
|---|---|---|
| N1 cron crash | **Fixed in code, not deployed.** `routes/run.py:cron_all_users` is implemented. | `tests/test_sources.py::test_cron_*`; `tests/test_postgres.py::test_cron_runs_every_user_with_their_own_key_and_history` (real Postgres: authorised GET, 2 users, own keys, own `cron` run rows, isolation) |
| N3 0% verified | **Addressed in design, unproven live.** The new `company_pages` provider discovers vacancies inside employers' own systems, the only kind that can reach Verified. | Unit tests only; the yield needs live runs after deployment |
| Overclaiming source label (new finding) | **Fixed.** Google Jobs called any off-board apply link "Company career page", and the ranking gave it the +25 company-page bonus. It is now "employer-site link (unconfirmed)" with +10. | `tests/test_priority.py::test_company_career_page_listing_outranks_portal_only` (updated to the corrected rule); `tests/test_config_http.py::test_google_jobs_normalisation` |
| Runs reported "ok" after discovery was cut short (new finding) | **Fixed.** Status is now `partial (search time limit)`. | `test_bounded_concurrency_and_partial_results_on_time_limit` |
| Politeness throttle not thread-safe with parallel discovery (new finding) | **Fixed.** Slots are reserved under a lock. | `test_polite_throttle_spaces_requests_per_host_across_threads` |
| Workday / SmartRecruiters boards searched with fixed data-role terms | **Fixed.** They use the user's roles. | `test_unsupported_board_is_not_an_error_and_board_terms_follow_user_roles` |
| Page-level "applications closed" text closed every posting on a multi-job careers page | **Prevented.** It applies only to single-vacancy pages. | `parse_jsonld_postings` |

### LaTeX resume feature: limitations

- **The in-browser PDF engine has a fixed package set.** titlesec, enumitem, marvosym, ragged2e and paracol are missing, so Jake's Resume fails in the browser. The page detects this before compiling and offers Overleaf. Enabling more packages would need a package proxy, i.e. one more server, which is not built.
- **The engine is third-party and young:** Siglum v0.1.4, MIT-licensed, loaded from jsDelivr and cdn.siglum.org. The first use downloads about 45 MB. Pinned to version 0.1.4.
- **Open in Overleaf** sends the `.tex` to Overleaf when the user clicks. There is no account connection, because Overleaf has no public write API.
- **Edit quality depends on the AI.** The guards make edits safe (wording only, no new commands, numbers or file access) but can't make them good. The user approves each one.
- **Recommendations** only consider tailored versions saved from a job card after this change, because older versions have no role or skill data.

### New limitations (by design)

- **LinkedIn and Naukri come only from Google search results.** Neither platform has a public job-search API, and both forbid scraping, so their pages are never fetched.
  - Coverage is whatever Google has indexed.
  - A result is skipped when the employer and title can't be read from Google's result title, and the title formats can change.
  - Experience is known only when the title or snippet states it.
  - These results are discovery evidence only: Needs Review unless the same vacancy is found in the employer's own system.
- **`company_pages` only covers some employers:** those already identified with official-website evidence, and the user's preferred companies (up to 3 new look-ups per run).
  - Careers pages rendered by JavaScript without `JobPosting` markup or an ATS link yield nothing. This is the same ceiling as verification.
  - The cap is 8 employers per run.
- **Paid searches cut off by the time limit still count.** SerpApi calls already in flight when the discovery deadline hits are spent, but their results are discarded.
- **Provenance only for new verification records.** Older records have no `checks.sources`; the dashboard falls back to the listing URL.

---

## P0: open, critical

### N1. Scheduled (cron) runs crash in multi-user mode: `cron_all_users` is undefined (fixed in code 2026-10-12, not deployed)
- **What:** `routes/run.py:49` (`do_GET`, Postgres branch) calls `cron_all_users()`, but this function is not defined anywhere in the repository and never has been (`git log -S "def cron_all_users"` returns nothing).
- **Effect:** every authorised Vercel cron call in multi-user mode raises `NameError`. Since commit `14fbb18`, `api/index.py` turns this into a JSON HTTP 500.
- **Evidence:**
  - code: an AST scan of `routes/run.py` lists `cron_all_users` as the only undefined name;
  - live: the production database has **0 runs with trigger `cron`**, against 10 dashboard runs between 2026-10-09 and 2026-10-10, although `vercel.json` schedules two crons per day.
- **Why the tests missed it:** `tests/test_vercel.py::test_run_endpoint_requires_cron_secret` only checks the 401 path. No test sends an authorised cron GET in Postgres mode.
- **Also unknown:** whether `CRON_SECRET` is set on Vercel. It is not in the local `.env`. Without it, `webapi.cron_ok` always returns False and cron gets 401 before reaching the crash.
- **Recommended fix (not applied in this audit):**
  - implement `cron_all_users()`: for each `backend.active_users()`, run `main.main(["--trigger", "cron", "--use-saved-settings", "--user-id", uid])` within the time budget;
  - add a test that sends an authorised GET with Postgres mode mocked.

  Note: 240 s cannot cover many users in one invocation. See FUTURE_SCOPE P0-2.

### N2. Standing credential hygiene
These were pasted into chat or screenshots during development and should be treated as exposed:
- the SerpApi key;
- the Groq key;
- the Neon database password;
- an earlier `SESSION_SECRET` (that one was regenerated);
- the Google service-account key.

No secret is committed to git (code: `.gitignore` covers `.env`, `*service-account*.json` and similar; `git log -- .env` is empty). Rotation is the owner's manual step.

---

## P1: open, affects daily use

### N3. The live verification yield is 0%: no job has ever reached "Verified"
- **Live:** 49 saved jobs, all `Needs Review`; 85 verification records, 77 `Needs Review` and 8 `Rejected`, **0 `Verified`**.
- **Grouped reasons (live, 85 records):**

  | Records | Reason | What it means |
  |---|---|---|
  | 47 | "official website not established" | No Knowledge Graph entry (32), or the entry has no website or doesn't match the employer (15). Small and regional employers fail the first gate. |
  | 15 | "careers page found, but no verifiable vacancy page or linked ATS board" | The employer's site was found, but not this specific vacancy. |
  | 6 | "no careers page or ATS link found on official domain" | |
  | 6 | "verification error (PermissionError)" | See N4. |
  | 8 | Rejected: older than the age limit | |
  | 1 | Vacancy not on the verified ATS board | |

- **Interpretation:** the pipeline is behaving as designed (it never upgrades on weak evidence), but for the jobs this user actually finds (Indian SMEs and staffing agencies), the strict gates never pass. "Verified" is effectively unreachable for most real results. This is a product-quality issue, not a correctness bug.
- **Next step:** see FUTURE_SCOPE P1-3.

### N4. Refusals by robots.txt / job-board URLs are reported as "verification error" and retried
- **Code:** `http_client.py:124-126` raises `PermissionError` to refuse a fetch. Some call path inside verification lets it escape to the generic handler at `verification/pipeline.py:38-42`.
- **Effect:** the job is labelled "verification error (PermissionError); check manually" and `retry=True`. A retry can never succeed, because robots.txt won't change.
- **Live:** 6 records.
- **Fix:** catch `PermissionError` at the fetch site and record "site does not allow automated checks", with `retry=False`.

### N5. A local diagnostic run is recorded in production run history and usage
- **What:** on 2026-10-09 at 18:08 IST, a local diagnostic run against Neon (SerpApi mocked, no credits spent) wrote a run row ("16 searches, ok") into one user's Runs history. It also added 16 to that key's monthly usage counter.
- **Effect:** the dashboard over-reports usage by 16, and the budget planner allows 16 fewer searches this month.
- **Fix:**
  - delete that single run row (`run_id 20261009-180903-c856d5`);
  - subtract 16 from the matching `serpapi_usage` row.

  This needs the owner's approval to write to production.
- **Prevention:** never point local runs at the production database; use the test database.

### N6. Run duration on Vercel is tight
- **Live:**
  - before `4cedc3b`, discovery used its whole 96 s share (40% of 240 s) after 5 of 15 queries; Vercel log: "discovery time budget used";
  - after `4cedc3b` (5 parallel workers), one run used its full 30-call allowance, found 44 candidates and finished in about 3 minutes.
- **Remaining:**
  - SerpApi calls still in flight when the cap hits are spent, but their results are discarded;
  - one run (17:46) ended `interrupted` for an unknown reason;
  - only one post-fix run has been observed.

---

## P2: limitations (by design or low impact)

| # | Issue | Evidence | Notes |
|---|---|---|---|
| N7 | Jobvite postings can never be Verified | code: `verification/ats_clients.py:31` (no public API; raises ValueError) | Permanent gap; they stay Needs Review. |
| N8 | SmartRecruiters client has no configured boards | code: `boards.json` has 19 boards: greenhouse 9, lever 6, ashby 2, workday 2, smartrecruiters **0** | Dead path until a board is added. |
| N9 | Workday uses an undocumented endpoint | code: `verification/ats_clients.py` | It can silently drop to zero coverage. |
| N10 | Rate limits and the politeness throttle are per instance | code: `webapi.py`, `http_client.py` | Fine at Hobby scale. |
| N11 | `.env.example` contains the real Google Sheet ID | code: `.env.example:17` | Hygiene only; access is controlled by sharing. |
| N12 | `rls_status()` only checks that the `app_rls` role exists and is grantable | code: `storage/pg.py:50-66` | It does not check that FORCE RLS and the policies exist on each table. Live: returns `enforced` on Neon, with all 4 migrations applied. |
| N13 | Verification evidence JSONL goes to `/tmp` on Vercel and is lost after the invocation | code: `main.py:354` and `webapi.prepare_env` | Durable evidence lives in the Postgres `verification.checks` column, which is the reviewable record. The schema is now documented in ARCHITECTURE.md. |
| N14 | `_resume_args` swallows every exception and silently falls back to default roles | code: `routes/run.py:34-38` | The user is not told that the resume roles weren't used. |
| N15 | The dashboard history table can show a mix of local-time and UTC run IDs | live: run IDs `20261009-180903` (local) vs `20261009-124319` (server, UTC) | The `started` column is consistent (IST); only IDs differ. Cosmetic. |
| N16 | No account has a username; the requested `admin` username account was never created | live: 0 of 5 users have a username | The owner creates it with `manage.py create-user … --username admin --admin`. |
| N17 | No application has ever been recorded | live: 0 rows in `applications`; 23 history rows | The lifecycle is tested but unused in production. |

## P3: cosmetic

- Tailoring reports how many suggestions it dropped, but not which ones.
- DOCX extraction is regex-based, so it may miss text in tables or nested runs.
- There is one CSS breakpoint (860px). No phone or keyboard-only test has been done.

---

## Previous findings (audit of 2026-10-09), re-checked

| Previous finding | Current status | Evidence | Fix commit / regression test | Remaining |
|---|---|---|---|---|
| `_resume_args()` crash in `routes/run.py` | **Resolved** | code: `def _resume_args(req)` at `routes/run.py:34`; live: Vercel log shows POST `/api/run` 500 three times at 18:06 (before), then 200 at 18:13, and a resume-roles run finishing `ok` with 44 candidates | `14fbb18`; `tests/test_run_route.py::test_resume_args_takes_request` calls the real function | N14 (silent fallback) |
| Test that mocked the broken function | **Superseded** | `tests/test_resume.py:121` still monkeypatches `_resume_args` for its own purpose, but a direct test now exists | `14fbb18` | None |
| Missing direct tests for applications/analytics | **Overstated before; covered** | `tests/test_lifecycle.py` directly tests stage changes and history, undo, validation, follow-up buckets, analytics from stored data, and archive/restore through the API | Pre-existing | No dedicated file, which is not needed |
| Groq never validated live | **Resolved for extraction; partially for tailoring** | live: 3 users have AI-built profiles with structured fields (summary, frameworks, certifications, experience_years), which are only written from `llm.extract_profile`; Vercel log shows `/api/tailor` 200 and `/api/ats` 200 at 18:05; model fix `c989c30` after a live 404 (retired model) | `c989c30` | Output quality and truthfulness not reviewed (personal data, deliberately not read) |
| SerpApi / ATS never validated live | **SerpApi resolved; ATS boards unknown** | live: 10 dashboard runs, 178 searches counted in Oct 2026, 44 candidates in one run; 91 company-cache entries | `1edf5d0`, `4cedc3b` | No live evidence of an ATS-board posting reaching Verified (N3) |
| Real Sheet ID in `.env.example` | **Open** | `.env.example:17` | None | N11 |
| RLS health reporting unconfirmed | **Resolved (with a limitation)** | `routes/health.py:29-30` calls `pg.rls_status()` and sets `ok=false` unless it returns "enforced"; live: returns `enforced` | Pre-existing | N12 |
| SmartRecruiters has no boards | **Open** | `boards.json` count | None | N8 |
| Jobvite cannot be verified | **Open (by design)** | `ats_clients.py:31` | None | N7 |
| Schedulers inactive | **Open and worse than reported** | systemd: no job-finder timers; Vercel cron: configured but crashes (N1); 0 cron runs | None | N1 |
| No Vercel deployment | **Resolved** | live: the owner supplied Vercel logs from `job-finder-obs14.vercel.app` showing `/api/*` traffic, signups, logins and searches | `edad190`, `891d7e3` and later | Monitoring is the Vercel log UI only |
| "This `.env` is single-user (no DATABASE_URL, SESSION_SECRET, LLM_API_KEY)" | **Outdated** | Local `.env` now sets DATABASE_URL, DATABASE_URL_UNPOOLED, SESSION_SECRET, SECRETS_KEY and LLM_API_KEY (names checked, values not read) | — | CRON_SECRET is not in the local `.env` |
