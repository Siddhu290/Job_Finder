# Testing and Deployment

**Audit date:** 2026-10-12 · **Commit:** `4cedc3b`, plus uncommitted source-priority work (not deployed)

## Test command and result

```bash
cd /home/sm/crjs/job-finder
.venv/bin/python -m pytest -q -rs
# 278 passed in 8.5s  (0 failed, 0 skipped)
```

History of the count:
- 233 at `9f4b6b3`;
- 238 at `4cedc3b` (baseline re-run before this work);
- 263 now: 24 in `tests/test_sources.py` and 1 Postgres cron integration test.

Two existing tests were updated to the corrected ranking rule (KNOWN_ISSUES "Update 2026-10-12"). The SerpApi fakes in `test_main.py` and `test_postgres.py` now key on the first Google Jobs query instead of the first call, because providers run in parallel; no assertion was relaxed.

How the suite is isolated:
- `tests/conftest.py` stops the real `.env` from being loaded and scrubs real-service variables.
- It also blocks every non-local socket, so the suite cannot reach SerpApi, Groq, Google or Neon.
- `tests/test_postgres.py` starts a throwaway local Postgres, applies the real Prisma migrations and checks RLS as a non-superuser.

## Coverage of important workflows

| Workflow | Direct tests | Gap |
|---|---|---|
| Search using a resume | `tests/test_run_route.py::test_resume_args_takes_request`; `tests/test_resume.py` | No end-to-end route test with a real store |
| Standard search / discovery | `tests/test_main.py`, `tests/test_run_route.py::test_discover_runs_searches_in_parallel` | — |
| Scheduled (cron) run, multi-user | `tests/test_sources.py::test_cron_*` (fairness, slices, deferral, env restore, auth); `tests/test_postgres.py::test_cron_runs_every_user_with_their_own_key_and_history` (real Postgres) | — |
| Source providers, caching, pagination, dedupe, provenance, evidence rules, dashboard source info | `tests/test_sources.py` (22) | No live provider test (by rule) |
| Verification gates | `tests/test_verification.py` (29) | PermissionError path (N4) |
| Status changes and undo | `tests/test_lifecycle.py` | — |
| Follow-ups | `test_lifecycle.py::test_followup_buckets_and_no_duplicates` | — |
| Analytics | `test_lifecycle.py::test_analytics_from_stored_data_only` | — |
| Resume parsing and AI errors | `tests/test_resume_parser.py`, `tests/test_resume.py` (missing key, model fallback) | Real output quality |
| Auth and account isolation | `tests/test_postgres.py`, `tests/test_isolation_guard.py`, `tests/test_tailor_auth.py` | — |
| API routes | `tests/test_vercel.py` | No browser/UI tests |
| Config validation | `tests/test_config_http.py` | — |
| Storage failure and recovery | `tests/test_store_budget.py` (stale runs, locks) | — |

## Environment variables

Checked by name only; values were not read.

| Variable | Local `.env` | Needed on Vercel (multi-user) |
|---|---|---|
| DATABASE_URL, DATABASE_URL_UNPOOLED | set | yes |
| SESSION_SECRET (≥ 32 chars) | set | yes |
| SECRETS_KEY (Fernet) | set | yes |
| SERPAPI_KEY | set | optional (admin and approved users' fallback) |
| LLM_API_KEY (Groq) | set | optional (same) |
| GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS / `_JSON` | set | optional (per-user Sheet tabs) |
| **CRON_SECRET** | **not set** | **yes, for cron**; Vercel status unknown |
| DISCOVERY_PROVIDERS, LINKEDIN_QUERIES, NAUKRI_QUERIES, COMPANY_PAGES_PER_RUN, CAREERS_TTL_DAYS, DISCOVERY_CONCURRENCY, SOURCE_TIERS, CRON_TIME_BUDGET, CRON_USER_SECONDS | not set (defaults) | optional, documented in `.env.example` |
| ALLOW_SIGNUP / INVITE_CODE | not set | sign-up policy |
| DASHBOARD_PASSWORD | set | single-user mode only |

**Warning:** the local `.env` points at the **production** Neon database. Any local run of `main.py` writes production data (KNOWN_ISSUES N5).

## Deployment state (evidence)

| Item | State | Evidence |
|---|---|---|
| Vercel production | **Deployed**, `job-finder-obs14.vercel.app` | Owner's Vercel request logs: login, register, run, resume, ats, tailor |
| Git → Vercel | Pushes to `main` on GitHub `Siddhu290/Job_Finder` auto-deploy | Commits `14fbb18`, `b059d03` and `4cedc3b` appeared live within minutes |
| Migrations | 0001-0004 applied on Neon | `_prisma_migrations` |
| Health | `/api/health` reports storage, `data_isolation` and registration | `routes/health.py`; live `rls_status` = enforced |
| Vercel cron | **Configured, never succeeded** | `vercel.json` (02:30 and 14:30 UTC); 0 cron runs; handler bug N1 |
| systemd timer | Not installed | `systemctl --user list-timers` has no job-finder timers |
| Deployment protection | Disabled by the owner (public sign-in page) | Owner's action on 2026-10-09 |
| Monitoring | Vercel log UI only | No alerting |

## Hands-on test, 2026-10-12

No paid calls, no production data, nothing deployed.

**1. Live, read-only, free endpoints** (no SerpApi, no database):
- The new code parsed 1,318 real postings from 8 curated boards (Greenhouse, Lever, Ashby, Workday) with 0 errors. Workday took 9 s.
- The careers crawl found Groww's official careers page and the Greenhouse board it links to.
- 0 jobs were relevant. That's correct: the postings were senior, outside India, or not data roles, e.g. "Principal Data Scientist" and "Senior Finance Data Analyst (Santa Clara)".

**2. Full search run on a throwaway local Postgres** (real migrations; SerpApi and websites faked; the project was copied without `.env`):
- All 5 providers ran; 7 candidates became 3 unique jobs.
- The vacancy seen on Google Jobs, LinkedIn and the employer's careers page became one job, canonical on the employer's board, and Verified.
- The Naukri-only job stayed Needs Review.
- A repeat run wrote 0 new rows.

**3. Dashboard in headless Chrome** (Playwright with system Chrome), 14 of 14 checks:
- 3 cards;
- "Official company posting" only on the evidence-backed cards;
- Greenhouse and LinkedIn chips, the verified Apply link to the employer board, and the Employer website link;
- the Naukri card is not official and its Apply is marked not verified;
- the Source filter and "Official postings first" work;
- source chips are reachable by keyboard;
- no horizontal scroll at 390 px;
- no console errors.

**Bugs found and fixed by this test:**
- One posting's two LinkedIn URL shapes were listed twice in provenance. Provenance is now deduplicated by source job ID.
- Needs Review jobs showed "Exp: Not stated" even when the listing stated it. It is now filled from the listing, and on rediscovery the "Not stated" placeholder is replaced; a real value is never overwritten.

## LaTeX resume feature: hands-on test, 2026-10-12

Run on the throwaway local database, in headless Chrome. Only the AI proposal was faked, since there was no Groq key.

**Result: 10 of 10 checks passed:**
- a pasted `.tex` is saved and tagged LaTeX;
- 2 proposed edits are shown with checkboxes;
- only the ticked edit is applied, and the rest of the file is byte-for-byte unchanged;
- Copy LaTeX fills the clipboard;
- Download `.tex` works;
- Open in Overleaf sends `encoded_snip` to overleaf.com/docs (intercepted in the test, so nothing reached Overleaf);
- a similar job recommends the saved tailored version, with its ATS score;
- **PDF in browser compiled a real PDF in about 12 s** (Siglum engine, downloaded from its CDN);
- the downloaded file is a valid PDF;
- there were no console errors.

**Also checked:**
- The plain-text template compiles in the browser: a 116 KB PDF.
- A Jake's-Resume-style `.tex` is identified straight away as needing titlesec, marvosym and enumitem, and Overleaf is offered.

**Bugs found and fixed:**
- The "Done" status was overwritten by the engine's background format caching.
- `\begin{center}{\Huge Name}` dropped the name from the plain text.
- Skill matching for recommendations was case-sensitive.
- The generated template used packages the browser engine lacks.

New tests: `tests/test_latex_resume.py` (15). They cover the edit guards (injection, new commands, numbers, braces, uniqueness, definitions), the re-check when applying, escaping, upload, plain text and recommendations.

## Safe local testing

- Run `pytest` only. It cannot reach the network or the real `.env`.
- **Don't run `main.py` locally against the current `.env`**: it points at production Neon. To exercise a real run locally, first create a Neon *branch* (or a local Postgres), point `DATABASE_URL` at it in a separate env file, and apply migrations there.
- No new migration was added by the source-priority work. Career-page cache entries live in the existing `company_cache` table.

## Deploying the source-priority work (needs the owner's approval)

1. Review the diff, then commit on a branch, **not** `main`, which auto-deploys.
2. Optionally use a Vercel preview deployment of the branch, with Preview env vars that point at a Neon branch, not production.
3. Merge to `main` to deploy.
4. Set `CRON_SECRET` on Vercel if it is missing.
5. Trigger one cron from Vercel → Cron Jobs.
6. Check the runs: a `cron` row per user (or "deferred"), and per-provider counts in the Vercel log summary.

## Validation still needed before calling it production-ready

1. Fix N1, set `CRON_SECRET`, trigger one cron manually from the Vercel dashboard, and confirm a `cron` row per user.
2. Rotate exposed credentials (N2).
3. Clean the phantom run (N5) with the owner's approval.
4. Observe 5 dashboard runs after `4cedc3b` (≤ 240 s, all `ok`).
5. Hand-check about 20 Needs Review jobs to plan the verification-yield work (N3).

None of these were done in this audit. Its rules were no deploys, no live API calls and no production writes.
