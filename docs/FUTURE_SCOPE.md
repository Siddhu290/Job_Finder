# Future Scope and Roadmap

**Audit date:** 2026-10-12 · **Commit:** `4cedc3b`, plus uncommitted source-priority work

**Done in code on 2026-10-12, not deployed:**
- P0-1 and P0-2 (cron);
- source-priority discovery: company career pages, LinkedIn and Naukri via Google, provenance, cross-source dedupe;
- honest Google Jobs label;
- partial-run status;
- dashboard source labels and filters.

What's left is listed below.

## Already built (don't rebuild)

- Multi-user Postgres with RLS
- Sign-up and sign-in
- Per-user encrypted keys and admin key sharing
- SerpApi discovery (parallel) plus ATS boards
- A multi-gate verification pipeline with stored evidence
- Retry queue
- Resume upload with Groq profile extraction and model fallback
- Match scores, ATS score and anti-fabrication tailoring
- Named resume collection
- Application lifecycle with undo
- Follow-ups and analytics
- Per-user Sheet tabs
- Vercel deployment with health check

Everything below closes a gap. None of it starts from scratch.

---

## P0: critical fixes

| ID | Item | Current status | User benefit | Dependencies | Complexity | Acceptance criteria | How to test |
|---|---|---|---|---|---|---|---|
| P0-1 | ~~Implement `cron_all_users()` (N1)~~ **done in code**: deploy after approval | Implemented and tested; not deployed | Twice-daily searches actually happen | None | Small | An authorised GET to `/api/run` returns 200 with one result per active user; a `cron` run row appears | New test: authorised GET in mocked Postgres mode. Live: Vercel → Cron Jobs → "Run" once, then check that the history row says `cron`. |
| P0-2 | ~~Fit multi-user cron into 300 s~~ **done in code**: per-user slices, least recently searched first, the rest deferred | Implemented and tested; not deployed | Every user gets their scheduled search | P0-1 | Small–Medium | Each cron invocation processes users round-robin (the least recently run first) until the time budget is spent; the rest go next slot | Unit test of the user ordering and time cut-off |
| P0-3 | Set `CRON_SECRET` on Vercel | Unknown | Without it, cron gets 401 | Owner | Trivial | Vercel env shows `CRON_SECRET` | `/api/health` cron flag, or one manual cron trigger |
| P0-4 | Rotate exposed credentials (N2) | Open | Prevents misuse of leaked keys | Owner | Small | New SerpApi key, Groq key, Neon password and service-account key are in Vercel and `.env`; old ones revoked | `/api/health` ok; one search |

## P1: needed before dependable daily use

| ID | Item | Current status | User benefit | Dependencies | Complexity | Acceptance criteria | How to test |
|---|---|---|---|---|---|---|---|
| P1-1 | Robots.txt / job-board refusals → a clear non-retry reason (N4) | Mislabelled as "verification error"; retried | Honest status; no wasted retries | None | Small | The reason reads "site does not allow automated checks"; `retry=False` | Unit test with a mocked robots disallow |
| P1-2 | Remove the diagnostic run row and its 16 phantom calls (N5) | Open | Correct history and budget | Owner approval for a production write | Trivial | Row gone; usage reduced by 16 | Read-only query before and after |
| P1-3 | Raise the live verification yield (N3) | 0 of 85 Verified; the `company_pages` provider (new) targets this, so **measure after deploying it** before changing gates | "Verified" becomes meaningful | Investigation first | Medium | Measure before changing: sample 20 Needs Review jobs by hand and record what evidence would legitimately verify each. Then add **one** evidence path that keeps the never-HTTP-200-alone rule, e.g. accepting an official domain from the employer's own ATS or apply-link domain when the apply URL sits on that domain. | Replay the sample offline (fixtures); target at least 25% Verified with 0 false Verified on the hand-checked set |
| P1-4 | Show when resume roles weren't used (N14) | Silent fallback | The user knows what was searched | None | Small | The run summary says "resume profile not found; used default roles" | Unit test |
| P1-5 | Stop local runs writing to production | The local `.env` points at Neon | Avoids repeats of N5 | None | Small | A local `.env.local` for a dev branch database; production URL only on Vercel | Check `.env` against the Neon branch |
| P1-6 | Observe 5 more live searches after `4cedc3b` | 1 observed | Confidence in the time budget | None | Trivial | Every run `ok`, ≤ 240 s, searches ≈ allowance | Read-only runs query |

## P2: useful improvements

| ID | Item | Current status | User benefit | Dependencies | Complexity | Acceptance criteria | How to test |
|---|---|---|---|---|---|---|---|
| P2-1 | Needs Review queue showing the evidence | Jobs list filter only; evidence not shown | Quick manual checks | None | Small | A card shows the gate that failed and the URLs checked (from `verification.checks`) | Snapshot of the API response |
| P2-2 | Recheck saved jobs for closure | Only at discovery time | Avoid applying to closed jobs | P0-1 | Medium | Saved jobs are rechecked every 3 days; closed ones are flagged | Unit test with a mocked closed page |
| P2-3 | Failure visibility: last-run banner and cron failure in Admin | Vercel logs only | Problems noticed without opening Vercel | P0-1 | Small | Admin view shows the last cron result per user | API test |
| P2-4 | `.env.example` placeholder sheet ID (N11) | Real ID | Hygiene | None | Trivial | Placeholder value | grep |
| P2-5 | `rls_status()` also checks FORCE RLS and the policies per table (N12) | Role check only | Catches a half-applied migration | None | Small | Health shows "NOT enforced: table X" if a policy is missing | Postgres test dropping a policy |
| P2-6 | Mobile and keyboard pass | Unknown | Usable on a phone | None | Small | Core flows work at 375px and with keyboard only | Manual checklist |
| P2-7 | Notifications (email digest) | Not implemented | Reminders without opening the app | **The owner chooses a provider** and accepts the privacy and cost | Medium | Opt-in, off by default | Mocked provider test |

## Source-priority follow-ups (from the 2026-10-12 work)

| ID | Item | Why | Acceptance criteria |
|---|---|---|---|
| S-1 | Measure the provider mix live | Provider value is unknown until real runs | 5 live runs; per-provider candidates, Verified count and parse-skip rate recorded from the run summary |
| S-2 | Track the LinkedIn/Naukri result-title parse rate | Google can change title formats | The run summary counts skipped (unparseable) results; alert when the rate exceeds 50% |
| S-3 | Seed `company_pages` from more employers (e.g. top fresher recruiters as a curated list) | Covers employers before anyone searched for them | A `companies.json` similar to `boards.json`, still resolved through Knowledge Graph/Wikidata evidence |
| S-4 | A licensed job-data provider for LinkedIn/Naukri, if one is ever needed | Google coverage is partial | Only with documented terms and the owner's approval of the cost |

## P3: optional

- Auto-tailor the resume when Apply is pressed (README future scope). This builds on `tailor.py`; keep the guards.
- Add SmartRecruiters boards (N8) and more Greenhouse/Lever companies to `boards.json`.
- Configurable match weights.
- A broader skill dictionary for non-data roles.
- Show which tailoring suggestions were dropped.
- Unify run-ID time zones (N15).
- Jobvite: permanent gap; only revisit if a public API appears.

## Order of work

1. P0-1, P0-2 and P0-3 together (cron).
2. P0-4 (rotate credentials).
3. P1-2 and P1-5 (clean data; separate dev database).
4. P1-1 and P1-4 (honest reasons).
5. P1-6 (observe runs).
6. P1-3 (verification yield, investigation first).
7. P2 items as needed.
