#!/usr/bin/env python3
"""Admin commands for multi-user (Postgres) mode. Uses DATABASE_URL from .env. Passwords are typed, never passed as arguments.

  python manage.py create-user EMAIL [--name NAME] [--admin]
  python manage.py list-users
  python manage.py disable-user EMAIL | enable-user EMAIL
  python manage.py reset-password EMAIL
  python manage.py import-sheet EMAIL      # copy the Google Sheet data (single-user setup) into this user's account

Schema changes are applied with Prisma: npx prisma migrate deploy (see README)."""
import argparse
import getpass
import sys

from dotenv import load_dotenv

import config

load_dotenv(config.PROJECT_DIR / ".env")


def _password():
    p1 = getpass.getpass("New password (10+ characters): ")
    if p1 != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match")
    return p1


def import_sheet(conn, user_id, sheet_store) -> dict:
    """Copy every tab of the single-user spreadsheet into one user's Postgres rows. Reads the sheet only."""
    from storage.pg import PgJobs, PgStore
    from integrations.google_sheets import HEADERS
    st, jobs = PgStore(conn, user_id), PgJobs(conn, user_id)
    data = sheet_store.read("Jobs", "Archive", "Details", "Verification", "Applications", "History", "Runs")
    row = lambda r: [r.get(h, "") for h in HEADERS]
    jobs.apply([row(r) for r in data["Jobs"] + data["Archive"]], [])
    archived = {r.get("Job ID") for r in data["Archive"]}
    if archived:
        jobs.archive(lambda r: r[0] in archived)
    strip = lambda rs: [{k: v for k, v in r.items() if k != "_row"} for r in rs]
    st.upsert("Details", strip(data["Details"]))
    st.upsert("Applications", strip(data["Applications"]))
    st.append("Verification", strip(data["Verification"]))
    st.append("History", [r if r.get("Action ID") else {**r, "Action ID": f"import-{i}"} for i, r in enumerate(strip(data["History"]))])
    st.append("Runs", [r for r in strip(data["Runs"]) if r.get("Run ID")])
    for doc in ("_settings", "_profile"):
        v = sheet_store.get_json(doc)
        if v:
            st.put_json(doc, v)
    return {k: len(v) for k, v in data.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("email")
    c.add_argument("--name", default="")
    c.add_argument("--admin", action="store_true")
    sub.add_parser("list-users")
    for name in ("disable-user", "enable-user", "reset-password", "import-sheet"):
        sub.add_parser(name).add_argument("email")
    args = ap.parse_args(argv)

    import accounts
    from storage import backend
    if not backend.is_pg():
        sys.exit("Multi-user mode is off: set DATABASE_URL (and STORAGE_BACKEND=postgres) in .env")
    conn = backend.conn()
    try:
        if args.cmd == "create-user":
            u = accounts.create_user(conn, args.email, _password(), args.name, "admin" if args.admin else "user")
            import sheet_mirror
            tab = sheet_mirror.tab_title(u["email"]) if sheet_mirror.create_tab(u["email"]) else None
            print(f"Created {u['role']} {u['email']}" + (f"; Google Sheet tab '{tab}' ready" if tab else ""))
        elif args.cmd == "list-users":
            for r in conn.execute("SELECT email, name, role, disabled, created_at, last_run_at FROM users ORDER BY created_at"):
                print(f"{r['email']:35} {r['role']:6} {'DISABLED' if r['disabled'] else 'active':8} created {r['created_at']:%Y-%m-%d}"
                      f"  last search {r['last_run_at']:%Y-%m-%d %H:%M}" if r["last_run_at"] else
                      f"{r['email']:35} {r['role']:6} {'DISABLED' if r['disabled'] else 'active':8} created {r['created_at']:%Y-%m-%d}")
        elif args.cmd in ("disable-user", "enable-user"):
            n = conn.execute("UPDATE users SET disabled = %s, session_version = session_version + 1 WHERE email = %s",
                             [args.cmd == "disable-user", accounts.clean_email(args.email)]).rowcount
            print("Done" if n else "No such user")
        elif args.cmd == "reset-password":
            n = conn.execute("UPDATE users SET password_hash = %s, session_version = session_version + 1, failed_logins = 0, "
                             "locked_until = NULL WHERE email = %s", [accounts.hash_password(_password()), accounts.clean_email(args.email)]).rowcount
            print("Password reset; existing sessions signed out" if n else "No such user")
        elif args.cmd == "import-sheet":
            from integrations.google_sheets import SheetsClient
            from storage.store import Store
            uid = backend.resolve_user(args.email)
            counts = import_sheet(conn, uid, Store(SheetsClient(config.load_config(require_serpapi=False)).open()))
            print("Imported (rows read from the sheet): " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    except (accounts.AccountError, ValueError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
