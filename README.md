# Fresher Data Job Finder

A job-search platform for fresher / entry-level roles in India. It discovers vacancies, **verifies the
employer's official application link**, scores each job against your resume, and tracks your applications.

It never applies for you, never submits forms or uploads resumes, and never contacts employers or recruiters.

---

## 1. How it works

```
 SerpApi Google Jobs ─┐                       ┌─ employer website (Wikidata / Knowledge Graph)
 Employer ATS boards ─┼─► filters ─► verify ──┼─ careers page ─► linked ATS board ─► exact vacancy ─► open?
                      │   (role, 0–1 yr,      └─ evidence + check-by-check result, retry queue
                      │    location/mode,
                      │    posted within)
                      ▼
            storage: Google Sheets (single-user)  OR  Neon Postgres (multi-user, row-level security)
                      ▼
 Dashboard (Vercel): Find Jobs · Saved · Applications · Follow-ups · Resume Lab · Analytics · Settings · Archive
```

- **Verification is separate from relevance.** A job can be a 95% resume match and still be unverified.
  Only **Verified** jobs get the green *Apply on company site* button. Everything else is a dashed
  *(not verified)* link.
- **Verified** means every one of these checks passed (each shown with its evidence in *Verification details*):
  - employer identified;
  - official website;
  - careers page;
  - the careers page links to the ATS board;
  - exact vacancy (title, location, requisition ID);
  - currently accepting applications;
  - direct apply URL on the employer's domain or board;
  - fresher / 0–1 years;
  - location / work mode.
- A failure caused by something temporary (out of search budget, network error) goes into a **retry queue**:
  up to 5 jobs per run, 3 attempts each, spaced 12 hours apart.

## 2. Two modes

| | Single-user (default) | Multi-user |
|---|---|---|
| Database | Google Sheets (`Jobs` tab + hidden tabs) | **Neon Postgres** (`DATABASE_URL`) |
| Sign-in | one dashboard password | email + password accounts |
| Data isolation | n/a | every row has `user_id`; **Postgres row-level security** (forced, also for the table owner) |
| SerpApi key | `.env` / saved in Settings | each user saves **their own key** in Settings (encrypted); admins may use the server key |
| Schema | — | **Prisma** (`prisma/schema.prisma`, migrations in `prisma/migrations`) |
| Google Sheet | the database (`Jobs` tab) | optional copy: **one tab per user**, `Jobs - <email>`, created with the account and synced after every search |

The app is Python. Prisma is used only for the schema and migrations, run from your machine. At runtime the
app talks to Postgres with `psycopg`.

## 3. Local setup (Ubuntu)

```bash
cd job-finder
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env        # fill in values; never commit .env
```

### Single-user (Google Sheets)
1. Google Cloud → enable the **Google Sheets API** → create a service account → *Keys → Add key → JSON*.
2. Save the key file, `chmod 600` it, and set `GOOGLE_CREDENTIALS=/path/to/key.json` in `.env`.
3. Share the spreadsheet with the service account's `client_email` as **Editor**.
4. Set `DASHBOARD_PASSWORD` and `SERPAPI_KEY`.

### Multi-user (Neon Postgres + Prisma)
1. Create a Neon project. Copy **both** connection strings: *pooled* goes in `DATABASE_URL` (used by the app),
   *direct* goes in `DIRECT_URL` (used by migrations).
2. Generate secrets:
   ```bash
   .venv/bin/python -c "import secrets;print(secrets.token_urlsafe(48))"                                  # SESSION_SECRET
   .venv/bin/python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"      # SECRETS_KEY
   ```
3. Apply the schema (Node 18+):
   ```bash
   npm install                       # installs the Prisma CLI (dev only)
   npx prisma migrate deploy         # applies 0001_init and 0002_row_level_security
   npx prisma migrate status
   ```
4. Create the first (admin) account. The password is typed at a prompt, never passed as an argument:
   ```bash
   .venv/bin/python manage.py create-user you@example.com --name "Your Name" --admin
   ```
5. Optional: copy your existing Google Sheet data into your account. This only reads the sheet:
   `.venv/bin/python manage.py import-sheet you@example.com`
6. More users: `manage.py create-user friend@example.com`, or set `INVITE_CODE` so people can register
   with the code. If `GOOGLE_SHEET_ID` and the service-account credentials are set, every new account gets
   its own tab `Jobs - <email>` in the spreadsheet. Their jobs are copied there after each search, and on
   *Settings → Sync now*. Nothing is ever deleted from a tab. There is no open sign-up, because searches spend SerpApi credits.
   Other admin commands: `list-users`, `disable-user`, `enable-user`, `reset-password`.

## 4. Running

```bash
.venv/bin/python dev_server.py                                   # dashboard at http://127.0.0.1:8000
.venv/bin/python main.py --check-sheets                          # single-user: read-only Sheets connection test
.venv/bin/python main.py --plan                                  # preview queries + SerpApi budget; spends NOTHING
.venv/bin/python main.py --dry-run --max-calls 5                 # search + verify, print results, write nothing
.venv/bin/python main.py                                         # live run (single-user)
.venv/bin/python main.py --user-id you@example.com               # live run for one user (multi-user)
.venv/bin/python main.py --use-saved-settings --user-id ...      # use the dashboard's saved Settings / resume
```
Search options:
- `--roles "Data Analyst;Business Analyst"`
- `--locations "Pune;Mumbai"`
- `--mode any|wfh|onsite`
- `--max-age-days 1|3|7|14|30`
- `--employment "full-time;internship"`
- `--exclude "sales"`
- `--prefer "Mastercard"`

Exit codes:

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | config / storage / auth error |
| 2 | finished with some API errors |
| 3 | another run is in progress |
| 130 | aborted |

### Tests
```bash
.venv/bin/python -m pytest -q
```
The suite has 221 tests and needs no network. `tests/test_postgres.py` starts its **own throwaway Postgres**
from local server binaries (`/usr/lib/postgresql/*/bin`), applies the real migrations and connects as a
non-superuser role. If no Postgres binaries are installed, those 12 tests are skipped.

## 5. Deploy to Vercel

Everything runs on Vercel: static dashboard (`public/`), Python API functions (`api/`) and the cron (`/api/run`).

```bash
npx vercel@latest login && npx vercel@latest link
# multi-user:
npx vercel@latest env add DATABASE_URL production        # Neon POOLED url
npx vercel@latest env add SESSION_SECRET production
npx vercel@latest env add SECRETS_KEY production
npx vercel@latest env add INVITE_CODE production         # optional
# single-user instead:  GOOGLE_SHEET_ID, DASHBOARD_PASSWORD, GOOGLE_CREDENTIALS_JSON (< key.json)
# both:
npx vercel@latest env add SERPAPI_KEY production         # optional in multi-user (admins only)
npx vercel@latest env add LLM_API_KEY production
npx vercel@latest env add CRON_SECRET production
npx vercel@latest --prod
```
After deploying, open `https://<your-app>/api/health`. It reports **which settings are present (true/false),
never their values**, plus the auth mode. Signed in, it also checks your storage.

Notes:
- `.vercelignore` keeps `.env`, keys, logs, tests, Prisma and Node files out of the upload.
- Migrations always run from your machine (`npx prisma migrate deploy`), never during a Vercel build.
- Security headers come from `vercel.json`: a strict Content-Security-Policy (scripts only from this site),
  `X-Frame-Options: DENY`, HSTS, `nosniff` and `no-referrer`.

## 6. Scheduling: pick exactly ONE

- **Vercel Cron** (in `vercel.json`): 02:30 and 14:30 UTC = **08:00 / 20:00 IST**.
  - Multi-user: each call serves users least-recently-searched first, sharing the 300 s limit. Users who
    don't fit are served first next time.
  - On the Hobby plan, a cron may start at any point within its scheduled hour.
- **Local systemd timer:** `scheduler/setup_schedule.sh install | status | run-now | disable | enable | uninstall`.
  It runs `main.py --use-saved-settings --trigger cron` and asks for confirmation, because running both
  schedulers doubles SerpApi usage.

Built-in protections:
- a per-user run lock with a 10-minute lease;
- a scheduled run is skipped if another succeeded in the last 30 minutes (duplicate cron calls);
- runs left "running" are marked *interrupted*;
- each run stops after 240 s on Vercel and still saves what it found.

## 7. SerpApi budget

- Each run uses at most `SERPAPI_MAX_CALLS`. Half goes to job searches, the rest to employer look-ups (cached
  30 days and shared between users) and HR look-ups.
- `SERPAPI_MONTHLY_LIMIT` is a safety limit **per SerpApi account**. Usage is counted per key fingerprint;
  the key itself is never stored for this.
- **Confirmed** numbers come from SerpApi's free account endpoint. **Estimated** numbers come from the app's
  own run records. They're reported separately.
- *Preview (free)* in Find Jobs (or `--plan`) shows exactly which searches a run would make.
- Keys are only ever changed by you, in Settings or `.env`. The app never rotates keys on its own.

## 8. Resume Lab & matching

- **Upload:** PDF or DOCX, at most 3 MB and 10 pages. The file is checked by its actual signature, parsed in
  memory and discarded. The text goes to the Groq API (`LLM_API_KEY`) to build an **editable** profile.
  Several profiles are allowed. Only the profile is stored; a copy of the text stays in *your browser*
  for tailoring.
- **Match score:** required skills 40, experience 20, role title 15, location/work mode 10, preferred skills 10,
  education 5. If the experience or location requirement fails, the job is marked **Not eligible** and its
  score is capped at 25.
- **Tailoring:** produces suggestions and a draft only, with checks against invented content:
  - a rewrite is dropped if it adds numbers that aren't in your resume;
  - a bullet suggestion must start from a real bullet of yours;
  - keywords you don't have are flagged as "add only if true".

  Export to DOCX or print to PDF. Approving a draft links that version to the application.

## 9. Security & privacy

- **Secrets stay on the server.** Logs redact keys. `/api/health` shows presence only.
- **Passwords:** scrypt hashes. 5 failed logins lock the account for 15 minutes, and the lock is stored in the
  database. Sessions are HMAC-signed, expire after 12 hours, and are revoked by changing your password or
  *Sign out everywhere*.
- **Isolation and storage:** row-level security on every user table. Users' SerpApi keys are Fernet-encrypted
  and only a hint like "…a1b2" is shown.
- **Input handling:** all input is validated. Request bodies are size-limited. The AI endpoints and searches
  are rate-limited (searches: 3 per 10 minutes). Login rate limiting is per instance, best effort.
- **Frontend:** no HTML injection (text only) and only http(s) links; external links open with `noopener`.
  Auth uses Bearer tokens rather than cookies, so CSRF doesn't apply.
- **Deleting data:** *Delete my account* removes the user and all their data (cascade). *Archive* never deletes.
- **Compromised credentials:** credentials previously pasted into chats should be treated as compromised.
  Rotate the SerpApi key, the Google service-account key and the dashboard password.

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `/api/health` → 503 | a required setting is missing (see which key is `false`) |
| "Permission denied for spreadsheet" | share the sheet with the service account's `client_email` as Editor |
| "No SerpApi key" | add your key in *Settings → SerpApi key* (admins: or set `SERPAPI_KEY`) |
| "Your saved SerpApi key can't be decrypted" | `SECRETS_KEY` changed; save the key again |
| Everyone signed out | `SESSION_SECRET` (multi-user) or `DASHBOARD_PASSWORD` (single-user) changed |
| `prepared statement … does not exist` | use Neon's **pooled** URL for `DATABASE_URL` (the app disables prepared statements) |
| Runs show "interrupted" | a run was killed (timeout / deploy); the next run marks it and continues |
| Many "Needs Review" | expected: unverifiable links are never promoted. Check the *Verification details* |

## 11. Rollback & recovery

- **Code:** redeploy a previous Vercel deployment (`vercel rollback`), or locally restore your backup / git
  history. The local snapshot taken before this upgrade is in the session scratchpad.
- **Database:** Neon has point-in-time restore / branches. Migrations are additive. To undo
  `0002_row_level_security`, drop the `user_isolation` policies (not recommended).
- **Sheets mode:** nothing is ever deleted; cleared jobs are in the `Archive` tab and can be restored from
  the dashboard.
- **Lost lock:** locks expire after 10 minutes by themselves.

## 12. Known limitations

- **Expect many Needs Review results.** Google's company panel, robots.txt and JavaScript-only careers pages
  often prevent full verification.
- **Vercel limits:**
  - On the Hobby plan, crons are imprecise and functions are limited to 300 s.
  - Multi-user cron serves as many users as fit per call.
  - Rate limiting for AI endpoints and searches is per instance (best effort); login lockout is in the database.
- **Recruiter profiles** come from Google results and are labelled *unverified*. LinkedIn is never accessed.
- **Resumes:** scanned (image) PDFs have no text, so use the DOCX instead.
- **Google Sheets in multi-user mode** is a one-way copy. Each user's tab is written from the database; edits
  made in the tab are not read back. The spreadsheet owner can see every user's tab, and users can switch the
  copy off in *Settings → My Google Sheet tab*.

## Project layout

```
main.py  config.py  models.py  filters.py  matching.py  priority.py  budget.py  analytics.py
applications.py  followups.py  settings.py  profiles.py  llm.py  tailor.py  resume_parser.py
accounts.py  user_secrets.py  sheet_mirror.py  http_client.py  webapi.py  dev_server.py  manage.py
discovery/      Google Jobs, ATS boards, HR search, queries
verification/   company → careers → ATS link → vacancy match → open status (pipeline.py)
storage/        store.py (Sheets tabs) · pg.py (Postgres) · backend.py (switch) · deduplication.py
integrations/   google_sheets.py
api/index.py    the single Vercel function: routes /api/<name> to routes/<name>.py (Hobby plan: max 12 functions)
routes/         jobs run action application resume tailor settings analytics login register account serpapi sheet health
public/         index.html app.css app.js
prisma/         schema.prisma, migrations/
scheduler/      setup_schedule.sh (systemd)
tests/          221 tests
```
