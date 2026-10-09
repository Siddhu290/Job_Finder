# Future Scope & Roadmap

Important correction to the original task framing: several "future" phases below (4, 7, 10, and parts of 2/3/8) are **already substantially implemented**, verified by code read + passing tests. This roadmap reflects actual ground truth, not the assumption that these are greenfield. Treat each phase as "close the gap," not "build from scratch," unless stated otherwise.

Priority key: **P0** security/data-integrity/major-failure · **P1** essential for dependable daily use · **P2** major usability/job-search improvement · **P3** optional/advanced, can wait.

---

## Phase 1 — Reliability and Production Readiness

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Fix `_resume_args()` signature bug (`routes/run.py`) | Open bug, reproduced | **P0** | None | Small | "Search using my resume" returns a valid job list, not a 500; new test calls the real function |
| API retries/timeouts/error handling | Already implemented (`http_client.py` retry/backoff, robots.txt, politeness) | — | — | — | No action needed |
| Idempotent runs / locking / dedup | Already implemented (run-lock, 30-min duplicate-skip, dedup module) | — | — | — | No action needed |
| SerpApi budget tracking/limits | Already implemented (`budget.py`) | — | — | — | No action needed |
| Structured logs / diagnostics | Already implemented (JSONL verification evidence, redacted logs) | P2 | — | Small | Confirm `write_audit`'s schema is documented (Needs Investigation today) |
| Config validation before running | Already implemented (`config.py` fails closed) | — | — | — | No action needed |
| Strengthen auth/session/file-upload | Already strong (scrypt, lockout, HMAC sessions, signature-checked uploads) | P2 | — | Small | Add IP-based login throttling if abuse is observed (currently per-account only, by design) |
| Rotate previously exposed credentials | README already states this policy explicitly | **P0** (standing policy) | None | Small | Rotate SerpApi key, Google service-account key, and dashboard password whenever any credential is pasted into a chat, ticket, or screen share |
| Test one scheduler before enabling recurring jobs | Neither scheduler currently active | **P1** | Fix P0 bug first | Small | One scheduler (systemd *or* Vercel cron, not both) runs once successfully end-to-end, confirmed via logs |
| Confirm persistence/recovery | Interrupted-run marking + 10-min lock lease already implemented and tested | — | — | — | No action needed |
| `.env.example` hygiene (real Sheet ID committed) | Open minor issue | P2 | None | Small | Replace with a placeholder like every other field in the file |

## Phase 2 — Better Job Matching

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Separate relevance from verification confidence | Already implemented (`matching.py` vs `verification/`, explicitly documented) | — | — | — | No action needed |
| Configurable role/location/mode/experience filters | Already implemented (`main.py --roles/--locations/--mode/--max-age-days/--employment`) | — | — | — | No action needed |
| Required vs preferred skills comparison | Already implemented (`matching.py` weighted scoring) | — | — | — | No action needed |
| Detect experience-requirement overreach | Already implemented (ineligibility cap at 25) | — | — | — | No action needed |
| Match explanations | Already implemented (`matching.py:132-147`) | — | — | — | No action needed |
| Transparent, configurable score-component weights | Partially implemented — weights exist and are shown, but are **hardcoded constants**, not user-configurable | P3 | None | Medium | User can adjust weight sliders in Settings; score recomputes live |
| Exclusions (senior roles, unwanted internships, ineligible locations) | Partially implemented — `--exclude` keyword flag exists; no structured "exclude internships" toggle | P2 | None | Small | A checkbox/flag excludes internship postings and user-specified locations without a keyword workaround |
| Expand the fixed skill dictionary beyond data/analytics roles | Not implemented | P3 | None | Medium | Matching works credibly for at least 2-3 additional role families (e.g., software/QA) without a code change per role |

## Phase 3 — Stronger Job Verification

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Official-domain/ATS-ownership checks | Already implemented and tested | — | — | — | No action needed |
| Evidence preservation per decision | Implemented (JSONL log); schema not yet documented | P2 | None | Small | `write_audit`'s format documented; spot-checked against a real log entry |
| Job-expiry detection / periodic rechecks | Partially implemented — `application_status.py` detects closed at verify-time; no scheduled recheck of previously-verified jobs | P2 | Scheduler active (Phase 1) | Medium | A verified job that later closes is detected within one scheduled cycle and flagged |
| Mismatched title/location/requisition-ID detection | Already implemented (`vacancy_matcher.py`) | — | — | — | No action needed |
| Specific reasons for "Needs Review" | Already implemented (pipeline returns per-gate failure reason) | — | — | — | No action needed |
| Manual review queue for uncertain jobs | Not implemented as a distinct UI — Needs Review jobs appear in the normal job list, not a dedicated queue | P2 | None | Small | A filterable "Needs Review" view with one-click re-verify |
| Suspicious-posting detection | Not implemented | P3 | None | Medium | At least one heuristic (e.g., no company resolvable + urgency language) flags a posting as suspicious with a stated reason |
| Jobvite support | Not implemented (no public API) | P3 | None | Large / low value | Document as a permanent known gap unless Jobvite publishes a usable API |
| SmartRecruiters real coverage | Client exists, zero boards configured | P3 | None | Small | At least one real SmartRecruiters board added to `boards.json` and verified end-to-end |

## Phase 4 — Application Tracking

**Already substantially implemented** — `applications.py`'s `STAGES` list (`Discovered, Saved, Ready to Apply, Applied, Online Assessment, Recruiter Screening, Technical Interview, HR Interview, Offer, Rejected, Withdrawn, Not Interested`) is a superset of the task's proposed lifecycle, with notes, recruiter, offer details, resume-version link, deadlines, and assessment/interview dates already as real fields, plus `undo`/`history`/archive.

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Core lifecycle + history/undo | Already implemented and exercised via `tests/test_lifecycle.py` | — | — | — | No action needed |
| Direct unit test coverage (`test_applications.py`) | Likely only indirectly covered | P1 | None | Small | A dedicated test exercises `clean_fields`, `apply_change`, `undo`, `history` directly, not through another module |
| Filters for pending applications / upcoming deadlines | `followups.py` already computes this; confirm it's surfaced as a dashboard filter, not just a backend computation | P2 | None | Small | Dashboard has a one-click "pending" / "due soon" filter backed by `followups.py` |
| "Application was submitted" honesty guarantee | Already correct by design — nothing auto-marks "Applied"; the user records it | — | — | — | No action needed |

## Phase 5 — Resume Lab

**Already substantially implemented**, with verified anti-fabrication guarantees.

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Resume-to-job comparison, missing-keyword suggestions | Already implemented (`ats.py`, `matching.py`) | — | — | — | No action needed |
| Role-specific resume summaries | Not confirmed as a distinct feature (tailoring covers per-job suggestions; a standalone "summary" generator wasn't found) | P3 | Groq live-tested first | Small | A one-paragraph role-targeted summary can be generated and is truthfulness-checked like other tailoring output |
| Draft bullet-point improvements grounded in real experience | Already implemented with enforced guards (`tailor.py`) | — | — | — | No action needed |
| Editable tailoring suggestions | Already implemented | — | — | — | No action needed |
| Resume version management (≤20, encrypted) | Already implemented | — | — | — | No action needed |
| DOCX export | Already implemented (README + `resumes.py`) | — | — | — | No action needed |
| PDF export | Implemented via browser print, not a server-generated PDF | P3 | None | Small | Acceptable as-is; only revisit if print-to-PDF proves unreliable for users |
| **Live Groq validation** | **Never done** — this blocks trusting every item above in production | **P0** (gating item for the whole phase) | A disposable Groq key | Small | One real resume, uploaded through the real UI, with a real Groq key, produces a sane profile/tailoring result end-to-end |

## Phase 6 — Follow-ups and Notifications

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Daily job-digest / reminder computation | Already implemented (`followups.py`: overdue/today/upcoming for follow-up, assessment, interview, deadline, closing-soon) | — | — | — | No action needed |
| Actually **notifying** the user (email/push) | **Not implemented at all** — no notification provider is wired up anywhere; reminders only appear when the dashboard is opened | P2 | Choice of provider (e.g., Resend/SendGrid for email) + explicit user opt-in | Medium | Before building: document provider, cost per email, and privacy implications (what job/application data would leave the server) for user sign-off |
| User-controlled frequency / opt-out | Not applicable yet (no notifications exist to configure) | P2 | Notification provider chosen | Small | A Settings toggle controls frequency and allows full opt-out, defaulting to opt-out |

**Explicitly flagged for the user before any implementation work, per task instructions:** this phase requires picking a notification provider, which has real cost and privacy implications (job search and application data would need to leave the server to reach an email/SMS/push provider). Recommend this be a separate decision, not bundled into a reliability pass.

## Phase 7 — Analytics

**Already substantially implemented.** `analytics.py` computes, from real stored data only: by-status, by-role, by-location, by-employment, by-source, by-posted-week, match-score distribution, application/assessment/interview/offer/rejection counts, application→interview and interview→offer conversion rates, and SerpApi usage (estimated + confirmed).

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Core metrics | Already implemented | — | — | — | No action needed |
| Direct unit test coverage (`test_analytics.py`) | Not confirmed to exist | P2 | None | Small | A dedicated test exercises each computed metric against known fixture data |
| "Follow-ups due" as an analytics tile | `followups.py` computes this; confirm it's surfaced on the Analytics page itself, not only the dashboard | P3 | None | Small | Analytics page shows a follow-ups-due count sourced from `followups.py` |

## Phase 8 — Recruiter Intelligence

**Already implemented to the exact spec the task describes**, conservatively: `hr_search.py` uses only Google's own result snippets to surface LinkedIn profile *links* (never fetched, never scraped), always labeled unverified, with no automatic contact of anyone.

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Public-source-only recruiter links, labeled unverified, user decides whether to contact | Already implemented and matches the task's constraints exactly | — | — | — | No action needed |

## Phase 9 — Dashboard Improvements

The 9 pages the task lists (Dashboard, Find Jobs, Saved Jobs, Applications, Follow-ups, Resume Lab, Analytics, Settings, Archive) **already exist** as real views in `public/app.js`'s view-dispatch table, plus an admin view. Remaining work is polish, not construction.

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| All 9 pages present | Already implemented | — | — | — | No action needed |
| Dark mode / responsive base | Already implemented, single breakpoint (860px) | P2 | None | Small | Verified visually on a phone-width viewport and a tablet-width viewport, not just one breakpoint |
| Loading states | Not confirmed — needs a UI pass | P2 | None | Small | Every async action shows a visible loading indicator, no silent dead time |
| Empty states | Not confirmed — needs a UI pass | P2 | None | Small | Every list page has a designed empty state, not a blank area |
| Error messages (user-facing) | Partially implemented — backend returns structured errors; frontend surfacing not audited in depth | P2 | None | Small | API errors render as a readable message, not a raw JSON dump or silent failure |
| Keyboard accessibility | Not confirmed | P3 | None | Medium | Core flows (login, search, apply status change) usable via keyboard alone |

## Phase 10 — Database and Scalability

**Already done — this is not future work.** The project already has a working Postgres backend (`storage/pg.py`) with enforced row-level security (migrations `0002`/`0003`, a dedicated non-bypassing DB role), used in multi-user mode, alongside the original Google Sheets backend for single-user mode — exactly the "preserve Sheets where useful, avoid two conflicting sources of truth" outcome the task asks to evaluate. The one-way Sheets mirror (`sheet_mirror.py`) is deliberately non-authoritative, so there is exactly one source of truth per account at a time.

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Postgres schema + RLS | Already implemented and tested against a real throwaway Postgres | — | — | — | No action needed |
| Backup/recovery documentation | README documents Neon point-in-time restore + migration rollback notes; not independently verified by running a restore | P2 | A Neon project | Small | A real restore-from-branch is performed once in a non-production project and documented |
| No further migration recommended | — | — | — | — | Do not propose moving single-user mode off Sheets; no clear benefit demonstrated |

## Phase 11 — Deployment and Monitoring

| Item | Current status | Priority | Dependencies | Complexity | Acceptance criteria |
|---|---|---|---|---|---|
| Reproducible deployment config | Already implemented (`vercel.json`, env var list documented in README/`.env.example`) | — | — | — | No action needed |
| Actual deployment | **Not done** — no evidence of a live Vercel deployment | **P1** | Fix P0 bug, do one Groq smoke test first | Small | `https://<app>/api/health` responds correctly in production |
| Protected API endpoints | Already implemented (session/bearer auth per route) | — | — | — | No action needed |
| Secure scheduled execution | Already implemented (`CRON_SECRET` bearer check) | — | — | — | No action needed |
| Health checks | Already implemented (`/api/health`, config-presence + storage reachability) | P2 | — | Small | Confirm it also surfaces Postgres `rls_status()` when RLS setup fails (currently unconfirmed — see `KNOWN_ISSUES.md`) |
| Run summaries | Partially implemented (JSONL verification logs); no human-readable per-run summary surfaced in the dashboard | P3 | None | Small | Dashboard shows a one-line summary of the last run (found/verified/errors) |
| Failure notifications | Not implemented (depends on Phase 6's notification provider decision) | P3 | Phase 6 | Medium | An operator is notified if a scheduled run fails outright (not just logged) |
| Deployment rollback | README documents `vercel rollback`; not exercised in this audit | P3 | A deployment to roll back | Small | One rollback performed and confirmed in a non-production deployment |
| Quota-exhaustion / failed-search monitoring | `budget.py` tracks and limits usage; no external alerting if a run silently finds 0 jobs due to exhausted quota | P2 | None | Small | A run that hits its SerpApi budget limit is visibly flagged in the dashboard, not just silently truncated |

---

## Recommended implementation order (across all phases)

1. **P0 — Fix `_resume_args()` bug** (Phase 1). Trivial, unblocks a real user-facing feature.
2. **P0 — One supervised live Groq smoke test** (Phase 5). Gates trust in the entire Resume Lab / tailoring feature set.
3. **P1 — Activate exactly one scheduler, once, deliberately** (Phase 1 / 11), then do one real Vercel deployment and confirm `/api/health` in production.
4. **P1 — Add direct unit tests for `applications.py` and `analytics.py`** (Phase 4 / 7) to close the only real test-coverage gap found in an otherwise well-tested codebase.
5. **P2 — `.env.example` hygiene, manual-review queue for Needs Review jobs, dashboard loading/empty/error-state pass, follow-up notifications decision (with explicit cost/privacy sign-off before building).**
6. **P3 — Everything else**: configurable match weights, structured exclusions, suspicious-posting heuristics, expanded skill dictionary, Jobvite/SmartRecruiters coverage, run summaries, rollback drill.
