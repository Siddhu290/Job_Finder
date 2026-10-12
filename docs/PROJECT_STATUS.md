# Project Status: Apply Seamlessly (fresher job finder)

**Audit date:** 2026-10-12
**Commit:** `4cedc3b` on `main`, working tree clean before the docs update
**Previous audit:** 2026-10-09 at `9f4b6b3`. Its findings are re-checked in `KNOWN_ISSUES.md`.

**Method:**
- read the code;
- ran the full local test suite;
- ran read-only, aggregate-only queries against the production Neon database (counts and grouped reasons; no personal fields read or printed; nothing written);
- used Vercel request logs supplied by the owner.

No live SerpApi or Groq calls were made, no deployment was done and no scheduler was changed.

## Update 2026-10-12: source-priority discovery

This work is uncommitted on top of `4cedc3b` and **not deployed**. Production behaves exactly as described below until it is reviewed, committed on a branch and deployed with the owner's approval. Tests: **263 passed** (baseline before the work: 238).

What changed:
- **Discovery is a provider registry**, in priority order and configurable with `DISCOVERY_PROVIDERS`:
  1. company career pages (new, free);
  2. curated ATS boards (free);
  3. Google Jobs;
  4. LinkedIn via Google search (new);
  5. Naukri via Google search (new).

  Tasks interleave round-robin. The paid search budget is shared round-robin. Concurrency is bounded and each provider's failures are isolated.
- **LinkedIn and Naukri pages are never fetched.** Only Google's result title, link and snippet are used, and those jobs are discovery-only until the employer's own system confirms them.
- **Provenance** (every source URL, with label, tier and ID) is stored as verification evidence.
- **Dedupe** makes the official URL canonical and keeps different requisitions apart.
- **The dashboard** shows "Official company posting" only from verification evidence, and adds source chips, a source filter and an "Official postings first" toggle.
- **Cron crash (N1) fixed in code**: a fair per-user schedule within the time limit.
- **Honesty fixes:**
  - an off-board Google Jobs apply link is no longer called "Company career page";
  - truncated runs are recorded as "partial", not "ok".

Details: `ARCHITECTURE.md` "Discovery sources" and `KNOWN_ISSUES.md` "Update 2026-10-12".

## Summary

The app is **deployed and in real use** on Vercel (`job-finder-obs14.vercel.app`) in multi-user Postgres mode:
- 5 accounts;
- 10 dashboard searches between 2026-10-09 and 2026-10-10;
- 49 saved jobs;
- 3 AI-built resume profiles.

The resume-search crash from the last audit is fixed. Live search, Groq profile extraction and row-level security are confirmed working in production.

Three things stop it being dependable:
1. **Scheduled runs have never worked.** The cron handler calls an undefined function (`cron_all_users`), and no cron run exists in production.
2. **No job has ever reached "Verified"** on live data. 0 of 85 verification records; most real employers fail the "official website" gate.
3. Run time on Vercel is tight. It was improved by parallel searches (`4cedc3b`), but only one post-fix run has been observed.

## Test result

```
cd /home/sm/crjs/job-finder && .venv/bin/python -m pytest -q -rs
238 passed in 4.24s   (0 failed, 0 skipped)
```

This is up from 233. The 5 new tests are:
- the regression test for `_resume_args` (`14fbb18`);
- the parallel discovery test (`4cedc3b`);
- 3 tests from the time-limit, match-filter and Groq-fallback commits (`1edf5d0`, `e7357ea`, `c989c30`).

## Live evidence (production, read-only)

| Fact | Value |
|---|---|
| Migrations applied | 0001_init, 0002_row_level_security, 0003_restricted_app_role, 0004_username_and_access_requests |
| `rls_status()` on production | `enforced` |
| Accounts | 5 (1 admin, 4 users; 2 approved to use the admin's keys; 0 with a username) |
| Runs | 10, all `dashboard`: 8 ok, 1 interrupted, 1 stopped early. **0 cron runs.** |
| SerpApi searches counted, Oct 2026 | 178, including 16 phantom calls from a local diagnostic run (KNOWN_ISSUES N5) |
| Jobs | 49, all Needs Review |
| Verification records | 77 Needs Review, 8 Rejected, **0 Verified** |
| Applications recorded | 0 |
| AI resume profiles | 3 users, with structured AI-extracted fields |
| Company cache entries | 91 |

## What changed since the last audit

| Commit | Change | Evidence |
|---|---|---|
| `1edf5d0` | Jobs found before the time limit are saved as Needs Review and retried; discovery time cap; fail-fast SerpApi retries | tests; live (17:20 run "stopped early" then later runs ok) |
| `e7357ea` | The match filter only applies once a profile exists | tests |
| `c989c30` | Current Groq model plus automatic fallback when a model is retired; resume upload keeps the file if the AI step fails | live: a 404 from the retired model was seen, then profiles were extracted |
| `14fbb18` | **`_resume_args` crash fixed**; `api/index.py` returns JSON errors instead of bare 500s | regression test; live: 500 at 18:06, then 200 and a successful run |
| `b059d03` | App renamed to "Apply Seamlessly" | owner's screenshot |
| `4cedc3b` | SerpApi searches run in parallel (5 workers) | test; live: 30 calls and 44 candidates in about 3 min, against 5 calls before |

## Readiness

| Area | Rating | Why |
|---|---|---|
| Local manual use | **Ready with limitations** | Tests pass. The local `.env` points at the **production** database, so local runs write production data (N5 happened this way). |
| Resume-based search | **Ready with limitations** | Fixed and confirmed live. If the profile is missing, it silently falls back to the default roles (N14). |
| Real AI resume analysis | **Ready with limitations** | Groq extraction is confirmed live for 3 users, and tailor and ATS endpoints returned 200 live. The quality and truthfulness of the output have not been reviewed. |
| Reliable job verification | **Not ready** | 0% Verified on live data; robots.txt refusals are mislabelled as errors (N3, N4). Company-originated discovery (not deployed) targets this; unproven live. |
| Daily automated searches | **Not ready** | The cron fix is written and tested but not deployed; `CRON_SECRET` on Vercel is unknown. |
| Multi-user production use | **Ready with limitations** | RLS is enforced live; sign-up, login, per-user keys and access requests are in use. Credentials were exposed during development (N2). |
| Vercel deployment | **Ready with limitations** | Deployed and serving. Monitoring is only the Vercel log UI; the cron path is broken. |
| Recovery and maintenance | **Ready with limitations** | Interrupted runs are marked, locks expire, and saved jobs survive the time limit. No restore drill has been done, and there are no failure alerts. |

See `FEATURE_MATRIX.md` for per-feature status, `FUTURE_SCOPE.md` for the prioritised plan, and `TESTING_AND_DEPLOYMENT.md` for commands and environment.

## Open Questions and Unverified Assumptions

| Question | Why it matters | Evidence now | Missing | Safest way to find out | Blocks |
|---|---|---|---|---|---|
| Is `CRON_SECRET` set on Vercel? | Without it, cron gets 401 | Not in the local `.env` | Vercel env listing | Owner checks Vercel → Settings → Environment Variables | Automation |
| Does cron work once N1 is fixed? | Daily searches | Handler is broken; 0 cron runs | Any successful cron run | After the fix: Vercel → Cron Jobs → Run, then a read-only runs query | Automation |
| Can multi-user cron fit in 300 s? | 5 users × about 3 min | 1 post-fix run took about 3 min | Design and measurement | Round-robin design (FUTURE_SCOPE P0-2), then observe | Automation |
| Why does no job reach Verified live? | Trust in "Verified" | Grouped reasons (KNOWN_ISSUES N3) | Hand-checked ground truth | Manually check about 20 Needs Review jobs | Reliable verification |
| Are the ATS board fetches (Greenhouse/Lever/Ashby/Workday) working live? | Free, reliable source | Unit tests only | Live log lines from `ats_boards` | Search the Vercel logs for "board" lines from a run | Quality only |
| Is the Groq output truthful and useful for real resumes? | Wrong roles mean wrong searches | 3 profiles exist (not read: personal data) | Human review | The owner reviews their own profile in Resume Lab | Resume quality |
| Does the live SerpApi schema still match? | Parsing | 44 candidates parsed on 2026-10-09 | — | Answered: yes, as of that date | — |
| Why did the 17:46 run end "interrupted"? | Lost runs | One row; no log for it | Vercel log for that time | Owner checks the Vercel logs around 17:46 IST on 2026-10-09 | Recovery confidence |
| Does `/api/health` catch a half-applied RLS migration? | Isolation | It checks the role only (N12) | Test with a missing policy | Postgres test (FUTURE_SCOPE P2-5) | Production hardening |
| Does the dashboard work on a phone and with a keyboard only? | Usability | Screenshots on desktop only | Device check | Manual checklist at 375px | None |
| Are any user-facing claims stronger than the evidence? | Honesty | The UI says "Verified" only for Verified jobs (0 so far); Needs Review jobs show their reason | — | Keep "Verified" strict; P1-1 fixes the misleading "verification error" label | None |
| Which limitations reduce job discovery most? | Results | 47 of 85 checks fail the website gate; Jobvite and SmartRecruiters are not covered; 7-day age filter | — | P1-3 investigation | Quality |
