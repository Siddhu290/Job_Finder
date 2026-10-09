#!/usr/bin/env python3
"""Fresher Data Job Finder: discover fresher Data Analyst / Data Engineer jobs, verify the employer's
official application URL and record results in Google Sheets. Never applies to anything."""
import argparse
import fcntl
import json
import logging
import os
import re
import threading
import logging.handlers
import signal
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import filters
import http_client
import budget
import matching
import priority
import user_secrets
from config import ConfigError, credentials_file_is_private, load_config
import config
from discovery import ats_boards, hr_search, query_builder
from discovery.serpapi_search import BudgetExhausted, SerpApi, SerpApiAuthError, SerpApiError, google_jobs
from integrations.google_sheets import C, HEADERS, SheetsClient, SheetsError, job_row, needs_headers, plan_sync
from models import BUDGET_NOTE, CLOSED, NEEDS_REVIEW, REJECTED, VERIFIED
from storage.deduplication import dedupe, job_id, job_key
from verification import pipeline
from storage import backend, store
from verification.company_resolver import CompanyCache

log = logging.getLogger("job_finder")
STOP = False


def _time_up():
    global STOP
    STOP = True
    log.warning("RUN_TIME_LIMIT reached: finishing current job, then saving results")


def _on_signal(signum, _frame):
    global STOP
    if STOP:
        raise KeyboardInterrupt
    STOP = True
    log.warning("received signal %s: finishing current job, then saving results (send again to abort)", signum)


RUN_CONTEXT = {"run_id": "-"}


class RunIdFilter(logging.Filter):
    def filter(self, record):
        record.run_id = RUN_CONTEXT["run_id"]
        return True


def setup_logging(log_dir, verbose):
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s run=%(run_id)s %(name)s: %(message)s")
    handlers = [logging.StreamHandler(sys.stderr),
                logging.handlers.RotatingFileHandler(log_dir / "job_finder.log", maxBytes=2_000_000, backupCount=5)]
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    if getattr(root, "_job_finder_logging", False):  # warm serverless process: handlers already attached
        return
    root._job_finder_logging = True
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(http_client.RedactingFilter())
        h.addFilter(RunIdFilter())
        root.addHandler(h)
    for noisy in ("urllib3", "google", "gspread"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def acquire_lock(cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    fh = open(cache_dir / "run.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    return fh


def discover(serp, stats, budget):
    raw = []
    for entry in ats_boards.load_boards(config.PROJECT_DIR / "boards.json"):
        if STOP:
            break
        raw += ats_boards.board_jobs(entry, stats)
    p = filters.PROFILE
    for q, where, wfh in query_builder.build(p.locations, p.mode, p.roles)[:budget]:  # deduplicated, best first
        if STOP:
            break
        try:
            found = google_jobs(serp, q, where, wfh)
            log.info("query %r -> %d results", q, len(found))
            raw += found
        except SerpApiAuthError:
            raise
        except SerpApiError as e:
            stats["errors"].append(str(e))
            log.warning("%s", e)
            if isinstance(e, BudgetExhausted):
                break
    return raw


def run(args):
    cfg = load_config(require_serpapi=False, require_sheets=not (args.dry_run or args.plan) and not backend.is_pg())
    split = lambda v: [x for x in (v or "").split(";") if x.strip()]
    profile = filters.set_profile(split(args.locations) or filters.DEFAULT_LOCATIONS, args.mode,
                                  split(args.roles), split(args.skills), args.max_years,
                                  max_age_days=args.max_age_days, employment_types=split(args.employment),
                                  exclude=split(args.exclude), prefer=split(args.prefer))
    log.info("search profile: %s, mode=%s, roles=%s", ", ".join(profile.locations), profile.mode,
             ", ".join(profile.roles) or "data analyst/engineer")
    if args.max_calls:
        cfg = replace(cfg, serpapi_max_calls=args.max_calls)
    if profile.max_age_days:
        cfg = replace(cfg, max_age_days=profile.max_age_days)
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(tz)
    today, now_s = now.date(), now.strftime("%Y-%m-%d %H:%M")
    stats = {"discovered": 0, "unique": 0, "rejected_filters": 0, "careers_pages": 0, VERIFIED: 0, NEEDS_REVIEW: 0,
             CLOSED: 0, REJECTED: 0, "new_rows": 0, "updated_cells": 0, "duplicates_skipped": 0, "errors": []}

    queries = query_builder.build(profile.locations, profile.mode, profile.roles)
    sheets = st = None
    if not (args.dry_run or args.plan):  # fail fast on storage problems before spending SerpApi credits
        sheets, st = backend.open_for_run(cfg, args.user_id)
        needs_headers(sheets.read())
    key, key_source = choose_serpapi_key(st, args.user_id)
    cfg = replace(cfg, serpapi_key=key)
    if st is not None:
        st.key_fp = user_secrets.fingerprint(key)   # usage is counted per SerpApi account
    log.info("SerpApi key: %s", {"own": "user's saved key", "server": "server key (SERPAPI_KEY)"}[key_source])
    acct = budget.account(cfg.serpapi_key)
    est_used = st.searches_used_this_month(now) if st else None
    b = budget.plan(cfg.serpapi_max_calls, budget.monthly_limit(), acct, est_used)
    stats["budget"] = b.as_dict()
    if args.plan:
        print_plan(queries, b, cfg)
        return 0
    if b.allowed <= 0:
        log.warning("no SerpApi budget for this run: %s", b.reason)
        print_summary(stats, args.dry_run)
        return 0
    cfg = replace(cfg, serpapi_max_calls=b.allowed)
    run_id = store.new_run_id()
    stats["run_id"] = run_id
    if st:
        RUN_CONTEXT["run_id"] = run_id
        if args.trigger == "cron" and st.recent_successful_run(now.replace(tzinfo=None)):
            log.warning("a run already finished in the last 30 minutes; skipping this scheduled run (duplicate cron call)")
            return 0
        if not st.acquire_lock(run_id):
            log.error("another run holds the lock (cron or dashboard); not starting a second one")
            return 3
        closed = st.close_stale_runs(now.replace(tzinfo=None))
        if closed:
            log.warning("marked %d earlier run(s) as interrupted", closed)
        st.append("Runs", [{"Run ID": run_id, "Started": now_s, "Trigger": args.trigger, "Status": "running",
                            "Profile": f"{'; '.join(profile.locations)} | {profile.mode} | {'; '.join(profile.roles) or 'data roles'}",
                            "Allowed Searches": b.allowed}])
    serp = SerpApi(cfg.serpapi_key, cfg.serpapi_max_calls)
    cache = CompanyCache(cfg.cache_dir / "companies.json")
    cache_in_sheet = sheets is not None and (os.getenv("CACHE_IN_SHEET") == "1" or backend.is_pg())
    if cache_in_sheet:
        cache.data.update(sheets.read_cache())
    raw = discover(serp, stats, budget=max(1, cfg.serpapi_max_calls // 2))
    stats["discovered"] = len(raw)
    if st:
        queued = st.retry_queue(now_s)
        stats["retried"] = len(queued)
        raw = queued + raw   # re-verify earlier transient failures first
    candidates, merged = dedupe(raw)
    stats["unique"] = len(candidates)
    stats["duplicates_skipped"] += merged

    # spend the limited employer-lookup budget on the most promising candidates first
    candidates.sort(key=lambda j: (filters.experience_check(j.description)[0] != filters.ELIGIBLE,
                                   all(http_client.is_job_board(u) for u in j.links)))
    hr_reserve = cfg.serpapi_max_calls // 5  # keep some searches for finding HR contacts
    serp.max_calls = cfg.serpapi_max_calls - hr_reserve
    kept = []
    for job in candidates:
        if STOP:
            break
        ok, why = filters.title_check(job.title)
        if ok and any(re.search(rf"\b{re.escape(k)}\b", job.company, re.I) for k in profile.exclude):
            ok, why = False, "excluded company keyword"
        if ok:
            ok, why = filters.employment_check(job.employment_type, job.title)
        if ok:
            ok, why = filters.location_check(job.location, job.description, job.remote)
        if ok:
            verdict, summary = filters.experience_check(job.description)
            ok, why = verdict != filters.TOO_SENIOR, (filters.contradiction(job.title, verdict, summary) or f"experience: {summary}")
        if not ok:
            stats["rejected_filters"] += 1
            log.info("filtered out: %s @ %s (%s)", job.title, job.company, why)
            continue
        pipeline.verify_job(job, serp, cache, stats)
        hits, total = filters.skill_match(job.description)
        if total:
            job.note(f"Resume match: {round(100 * len(hits) / total)}% ({', '.join(hits[:8]) or 'no listed skills mentioned'})")
        emails = priority.published_emails(job.description)
        if emails:
            job.note(f"HR email (published in listing): {', '.join(emails)}")
            kind = "published" if job.status == VERIFIED else "listing"   # employer's own posting vs portal copy
            job.contacts += [{"type": kind, "value": e, "evidence": job.apply_url or job.listing_url, "found": today.isoformat()}
                             for e in emails]
        if job.status != VERIFIED and job.status != CLOSED and not filters.is_fresh(job.posted_date, cfg.max_age_days, today):
            job.status = REJECTED
            job.notes.insert(0, f"posted {job.posted_date}, older than {cfg.max_age_days} days and not verified open")
        if job.status == REJECTED:
            stats["rejected_filters"] += 1
        kept.append(job)
        log.info("%s: %s @ %s | %s", job.status, job.title, job.company, job.notes[0] if job.notes else "")
    serp.max_calls = cfg.serpapi_max_calls
    add_hr_contacts(kept, serp, cache, stats)
    cache.save()
    if cache_in_sheet:
        sheets.write_cache(cache.data)

    final, merged = dedupe(kept, key=job_key)
    stats["duplicates_skipped"] += merged
    for j in final:
        stats[j.status] = stats.get(j.status, 0) + 1
    write_audit(cfg.log_dir, now, final, args.dry_run)

    if args.dry_run:
        print_results(final)
    else:
        values = sheets.read()  # re-read right before writing to see the user's latest edits
        if needs_headers(values):
            sheets.write_headers()
            values = [list(HEADERS)]
        recheck_records = []
        rechecks = recheck_verified_rows(values, {job_id(j) for j in final}, recheck_records, run_id, now_s)
        appends, updates, dupes = plan_sync(values, final, rechecks, now_s, sheets.read_archive())
        sheets.apply(appends, updates)
        stats.update(new_rows=len(appends), updated_cells=len(updates))
        stats["duplicates_skipped"] += dupes
        st.upsert("Details", [details_record(j, now_s) for j in final])
        if backend.is_pg():
            mirror_to_sheet(sheets, st, args.user_id, stats)
        st.append("Verification", [verification_record(j, run_id, now_s) for j in final] + recheck_records)
    stats["serpapi_calls"] = serp.calls
    if st:
        st.upsert("Runs", [{"Run ID": run_id, "Finished": datetime.now(tz).strftime("%Y-%m-%d %H:%M"), "SerpApi Calls": serp.calls,
                            "Discovered": stats["discovered"], "Unique": stats["unique"], "New Rows": stats["new_rows"],
                            "Verified": stats.get(VERIFIED, 0), "Needs Review": stats.get(NEEDS_REVIEW, 0),
                            "Errors": len(stats["errors"]), "Status": "stopped early (time limit)" if STOP else "ok"}], key="Run ID")
        if hasattr(st, "add_usage"):
            st.add_usage(now, serp.calls)   # shared monthly SerpApi counter (multi-user mode)
        st.release_lock(run_id)
    print_summary(stats, args.dry_run)
    return 0 if not stats["errors"] else 2


def add_hr_contacts(jobs, serp, cache, stats):
    """HR profiles (from Google results) for the best-ranked jobs, until the SerpApi budget runs out."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ranked = sorted((j for j in jobs if j.status in (VERIFIED, NEEDS_REVIEW) and j.notes and j.notes[0] != BUDGET_NOTE),
                    key=lambda j: -priority.score(dict(zip(HEADERS, job_row(j, now))))[0])
    for job in ranked:
        if STOP or not job.company:
            continue
        try:
            profiles = hr_search.find_hr(job.company, serp, cache)
        except BudgetExhausted:
            break
        except SerpApiError as e:
            stats["errors"].append(f"HR search {job.company}: {e}")
            continue
        if profiles:
            job.note(hr_search.note(profiles))
            job.contacts += [{"type": "profile", "name": n, "role": h, "value": u, "found": datetime.now().date().isoformat(),
                              "evidence": f"Google results for '{job.company} HR recruiter'"} for n, h, u in profiles]
            stats["hr_found"] = stats.get("hr_found", 0) + 1


def details_record(j, now_s):
    a = matching.analyze_job(j.description)
    return {"Job ID": job_id(j), "Updated": now_s, "Description": j.description[:20000],
            "Required Skills": ", ".join(a["required"]), "Preferred Skills": ", ".join(a["preferred"]),
            "Min Years": "" if a["min_years"] is None else a["min_years"], "Education": ", ".join(a["education"]),
            "Closes": j.closes, "Contacts": j.contacts}


def verification_record(j, run_id, now_s):
    retry = j.retry and j.status == NEEDS_REVIEW
    attempts = j.attempts + 1
    nxt = (datetime.strptime(now_s, "%Y-%m-%d %H:%M") + timedelta(hours=12 * attempts)).strftime("%Y-%m-%d %H:%M") if retry else ""
    is_open = j.checks.get("open_status", {}).get("status") == "pass"
    return {"Timestamp": now_s, "Job ID": job_id(j), "Run ID": run_id, "Status": j.status, "Req ID": j.req_id,
            "Reason": j.notes[0] if j.notes else "", "Checks": j.checks, "Last Open Check": now_s if is_open else "",
            "Retry": "yes" if retry else "", "Attempts": attempts, "Next Check": nxt}


def recheck_verified_rows(values, current_ids, records=None, run_id="", now_s=""):
    """Previously Verified rows not rediscovered this run: re-check the employer system directly (no SerpApi)."""
    out = {}
    for n, r in enumerate(values[1:], start=2):
        r = r + [""] * (len(HEADERS) - len(r))
        if STOP or r[C["Verification Status"]] != VERIFIED or r[C["Job ID"]] in current_ids or not r[C["Official Apply URL"]]:
            continue
        state, ev = pipeline.recheck(r[C["Official Apply URL"]], r[C["Notes"]])
        log.info("recheck row %d (%s): %s - %s", n, r[C["Job Title"]], state, ev)
        if records is not None and state in ("open", "closed"):
            records.append({"Timestamp": now_s, "Job ID": r[C["Job ID"]], "Run ID": run_id,
                            "Status": VERIFIED if state == "open" else CLOSED, "Reason": f"re-check: {ev}"[:500],
                            "Checks": {"open_status": {"status": "pass" if state == "open" else "fail", "detail": ev[:300],
                                                       "url": r[C["Official Apply URL"]]}},
                            "Last Open Check": now_s if state == "open" else "", "Attempts": 1})
        if state in ("open", "closed"):
            out[n] = state
    return out


def write_audit(log_dir, now, jobs, dry_run):
    path = log_dir / f"verification-{now:%Y-%m-%d}.jsonl"
    with open(path, "a") as f:
        for j in jobs:
            f.write(json.dumps({"run": now.isoformat(), "dry_run": dry_run, "job_id": job_id(j), "status": j.status,
                                "title": j.title, "company": j.company, "location": j.location, "experience": j.experience,
                                "listing_url": j.listing_url, "careers_url": j.careers_url,
                                "apply_url": j.apply_url if j.status == VERIFIED else "", "notes": j.notes,
                                "evidence": j.evidence}) + "\n")
    log.info("audit evidence written to %s", path)


def print_results(jobs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ranked = [(priority.score(dict(zip(HEADERS, job_row(j, now)))), j) for j in jobs]
    for (pts, label, why), j in sorted(ranked, key=lambda x: -x[0][0]):
        print(f"\n[{label} {pts}] [{j.status}] {j.title} | {j.company} | {j.location} | exp: {j.experience or 'Not stated'}")
        print(f"  why:     {', '.join(why)}")
        print(f"  listing: {j.listing_url}")
        if j.careers_url:
            print(f"  careers: {j.careers_url}")
        if j.status == VERIFIED:
            print(f"  APPLY:   {j.apply_url}")
        print(f"  reason:  {j.notes[0] if j.notes else ''}")


def mirror_to_sheet(jobs_client, st, user_ref, stats):
    """Multi-user: copy this user's jobs to their own tab in the Google spreadsheet (never fails the run)."""
    import sheet_mirror
    if not sheet_mirror.configured() or (st.get_json("_settings") or {}).get("sheet_mirror") is False:
        return
    try:
        out = sheet_mirror.sync_user(backend.user_email(backend.resolve_user(user_ref)), jobs_client.read()[1:])
        log.info("synced %s: %d added, %d updated", out["tab"], out["added"], out["updated"])
    except Exception as e:  # noqa: BLE001
        stats["errors"].append(f"Google Sheet sync: {type(e).__name__}: {e}"[:300])


def choose_serpapi_key(st, user_ref=None) -> tuple:
    """The user's saved key (Settings) first; else the server key (admins only in multi-user mode)."""
    multi = backend.is_pg()
    uid = backend.resolve_user(user_ref) if multi and user_ref else None
    if st is None:
        try:   # plan / dry run: still use the user's saved key if storage is reachable
            st = backend.open_store(uid) if (uid or not multi) else None
        except Exception:  # noqa: BLE001 - no storage: fall back to the server key
            st = None
    is_admin = backend.may_use_server_keys(uid) if uid else not multi   # admins and approved users may share
    key, source = user_secrets.key_for_run(st, multi, is_admin)
    if not key:
        raise ConfigError("No SerpApi key: add your key in Settings → SerpApi key"
                          + ("" if multi else " (or set SERPAPI_KEY in .env)"))
    return key, source


def saved_settings_args(user_ref=None) -> list:
    """CLI arguments from the saved settings / active resume profile; [] if storage can't be read (defaults then apply)."""
    import profiles
    import settings
    try:
        st = backend.open_store(backend.resolve_user(user_ref) if backend.is_pg() else None)
        return settings.run_args(settings.clean(st.get_json("_settings"))) + profiles.search_args(profiles.load(st.get_json("_profile")))
    except Exception as e:  # noqa: BLE001 - fall back to defaults, but say so
        log.warning("could not load saved settings (%s); using defaults", type(e).__name__)
        return []


def print_plan(queries, b, cfg):
    disc = max(1, b.allowed // 2)
    print("==== Search plan (no searches spent) ====")
    print(f"  Searches allowed this run: {b.allowed}  ({b.reason})")
    print(f"  SerpApi account: {b.confirmed_left if b.confirmed_left is not None else 'unknown'} searches left (confirmed), "
          f"{b.confirmed_used if b.confirmed_used is not None else 'unknown'} used this month (confirmed); "
          f"{b.estimated_used if b.estimated_used is not None else 'n/a'} used per our run records (estimated)")
    print(f"  Up to {min(disc, len(queries))} job searches, then up to {b.allowed - min(disc, len(queries)) - b.allowed // 5} employer look-ups "
          f"(cached ones are free) and up to {b.allowed // 5} HR look-ups")
    for i, (q, where, wfh) in enumerate(queries[:disc], 1):
        print(f"   {i:2}. {q}" + ("  [work from home filter]" if wfh else ""))
    if len(queries) > disc:
        print(f"   … {len(queries) - disc} more queries not run this time (budget)")


def print_summary(s, dry_run):
    print("\n==== Run summary" + (" (DRY RUN - nothing written)" if dry_run else "") + " ====")
    rows = [("Candidates discovered", s["discovered"]), ("Unique jobs", s["unique"]),
            ("Rejected by experience/location/title/age filters", s["rejected_filters"]),
            ("Official careers pages found", s["careers_pages"]), ("Verified vacancies", s[VERIFIED]),
            ("Needs manual review", s[NEEDS_REVIEW]), ("Closed", s[CLOSED]),
            ("New rows written", s["new_rows"]), ("Existing-row cells updated", s["updated_cells"]),
            ("Duplicates skipped/merged", s["duplicates_skipped"]), ("SerpApi calls used", s.get("serpapi_calls", 0)),
            ("Left unverified: SerpApi budget used up", s.get("budget_skipped", 0)),
            ("Jobs with HR LinkedIn profiles found", s.get("hr_found", 0)),
            ("API/verification errors", len(s["errors"]))]
    for k, v in rows:
        print(f"  {k:<52}{v}")
    for e in s["errors"][:20]:
        print(f"    ! {http_client.redact(e)}")


def check_sheets():
    cfg = load_config(require_serpapi=False, require_sheets=True)
    client = SheetsClient(cfg).open(create_worksheet=False)
    values = client.read()
    if needs_headers(values):
        print(f"OK: connected as {client.email}. Worksheet '{cfg.worksheet}' is empty; headers will be written on the first live run.")
    else:
        print(f"OK: connected as {client.email}. Worksheet '{cfg.worksheet}' headers valid, {len(values) - 1} data rows.")
    if not credentials_file_is_private(cfg.credentials_path):
        print(f"WARNING: {cfg.credentials_path} is readable by other users; run: chmod 600 {cfg.credentials_path}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="discover and verify, print results, write nothing to Sheets")
    ap.add_argument("--check-sheets", action="store_true", help="read-only Google Sheets connection and header test")
    ap.add_argument("--max-calls", type=int, help="override SERPAPI_MAX_CALLS for this run")
    ap.add_argument("--locations", help='semicolon-separated, e.g. "Pune;Mumbai" (default Pune;Bengaluru;Nashik)')
    ap.add_argument("--roles", help='semicolon-separated job roles (from the resume); default data analyst/engineer')
    ap.add_argument("--skills", help="semicolon-separated skills used for the resume match score")
    ap.add_argument("--max-years", type=float, default=1, help="maximum experience a job may ask for (default 1)")
    ap.add_argument("--max-age-days", type=int, choices=[1, 3, 7, 14, 30], help="posted within N days (default JOB_MAX_AGE_DAYS)")
    ap.add_argument("--employment", help='semicolon-separated: full-time;internship;contract;part-time;graduate program')
    ap.add_argument("--exclude", help="semicolon-separated keywords that disqualify a job title or company")
    ap.add_argument("--prefer", help="semicolon-separated preferred companies (ranked higher)")
    ap.add_argument("--plan", action="store_true", help="preview queries and SerpApi budget; spends no searches")
    ap.add_argument("--trigger", default="cli", help=argparse.SUPPRESS)
    ap.add_argument("--user-id", help="multi-user mode: the user (email or id) this run is for")
    ap.add_argument("--use-saved-settings", action="store_true",
                    help="use the dashboard's saved Settings and active resume profile (for scheduled runs)")
    ap.add_argument("--mode", choices=filters.MODES, default="any",
                    help="any = office/hybrid in the locations + work from home anywhere in India; wfh; onsite")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.use_saved_settings:
        extra = saved_settings_args(args.user_id)
        args = ap.parse_args([a for a in (argv if argv is not None else sys.argv[1:]) if a != "--use-saved-settings"] + extra)

    try:
        cfg_dirs = load_config(require_serpapi=False, require_sheets=False)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 1
    setup_logging(cfg_dirs.log_dir, args.verbose)
    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
    except ValueError:
        pass  # not the main thread (e.g. inside a serverless request handler)
    global STOP
    STOP = False  # a warm serverless process may have stopped a previous run
    timer = None
    limit = float(os.getenv("RUN_TIME_LIMIT", "0"))
    if limit:  # serverless hosts kill long runs: stop discovering/verifying in time to save results
        timer = threading.Timer(limit, _time_up)
        timer.daemon = True
        timer.start()

    lock = acquire_lock(cfg_dirs.cache_dir)
    if lock is None:
        log.error("another job-finder run is in progress; exiting")
        if timer:
            timer.cancel()
        return 3
    try:
        return check_sheets() if args.check_sheets else run(args)
    except (ConfigError, SheetsError) as e:
        log.error("%s", e)
        return 1
    except SerpApiAuthError as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        log.error("aborted by user")
        return 130
    finally:
        if timer:
            timer.cancel()
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
