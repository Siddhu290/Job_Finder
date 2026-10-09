"""User accounts for the multi-user (Postgres) mode: password hashing, login lock-out, signed sessions.

- Passwords: scrypt (stdlib), per-user random salt, constant-time comparison. Minimum 10 characters.
- Lock-out: 5 failed logins lock the account for 15 minutes. Stored in the database, so it survives cold starts.
- Sessions: "<user_id>.<session_version>.<expiry>.<hmac>" signed with SESSION_SECRET. Bumping session_version
  (password change / "sign out everywhere") invalidates every existing token for that user.
- Accounts are created by an admin (manage.py) or self-registration with INVITE_CODE; there is no open sign-up."""
import base64
import hashlib
import hmac
import os
import re
import time
import uuid

MIN_PASSWORD = 10
MAX_FAILED = 5
LOCK_MINUTES = 15
SESSION_HOURS = 12
_EMAIL = re.compile(r"^[^@\s<>]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


class AccountError(ValueError):
    pass


# ---------- passwords ----------
def hash_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"Password must be at least {MIN_PASSWORD} characters")
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt((password or "").encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        raise AccountError("Enter a valid email address")
    return email


# ---------- sessions ----------
def _secret() -> bytes:
    s = os.environ.get("SESSION_SECRET", "")
    if len(s) < 32:
        raise AccountError("SESSION_SECRET must be set to a random string of at least 32 characters")
    return s.encode()


def issue_token(user_id: str, session_version: int, now=None) -> str:
    exp = int((now or time.time()) + SESSION_HOURS * 3600)
    payload = f"{user_id}.{session_version}.{exp}"
    return payload + "." + hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def parse_token(token: str, now=None):
    """(user_id, session_version) if the signature and expiry are valid, else None. The caller must still check
    the user exists, is enabled and has the same session_version."""
    try:
        user_id, ver, exp, sig = token.split(".")
        payload = f"{user_id}.{ver}.{exp}"
        if not hmac.compare_digest(sig, hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()):
            return None
        if int(exp) <= (now or time.time()):
            return None
        return str(uuid.UUID(user_id)), int(ver)
    except (ValueError, AttributeError, AccountError):
        return None


# ---------- database operations (users table has no RLS; only this module touches it) ----------
def create_user(conn, email: str, password: str, name: str = "", role: str = "user") -> dict:
    email = clean_email(email)
    if role not in ("user", "admin"):
        raise AccountError("role must be user or admin")
    with conn.transaction():
        if conn.execute("SELECT 1 FROM users WHERE email = %s", [email]).fetchone():
            raise AccountError("An account with this email already exists")
        uid = str(uuid.uuid4())
        conn.execute("INSERT INTO users (id, email, name, password_hash, role) VALUES (%s, %s, %s, %s, %s)",
                     [uid, email, (name or "")[:80], hash_password(password), role])
    return {"id": uid, "email": email, "name": name, "role": role}


def authenticate(conn, email: str, password: str) -> dict:
    """Returns the user or raises AccountError with a message that doesn't reveal whether the email exists.
    The failure counter is committed BEFORE the error is raised (raising inside the transaction would roll it back)."""
    bad = AccountError("Wrong email or password")
    try:
        email = clean_email(email)
    except AccountError:
        raise bad from None
    error = None
    with conn.transaction():
        u = conn.execute("SELECT *, (locked_until IS NOT NULL AND locked_until > now()) AS locked FROM users WHERE email = %s FOR UPDATE",
                         [email]).fetchone()
        if not u:
            verify_password(password, "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA")  # similar timing for unknown emails
            error = bad
        elif u["disabled"]:
            error = bad
        elif u["locked"]:
            error = AccountError(f"Too many failed attempts; try again in {LOCK_MINUTES} minutes")
        elif not verify_password(password, u["password_hash"]):
            failed = u["failed_logins"] + 1
            if failed >= MAX_FAILED:
                conn.execute("UPDATE users SET failed_logins = 0, locked_until = now() + make_interval(mins => %s) WHERE id = %s",
                             [LOCK_MINUTES, u["id"]])
            else:
                conn.execute("UPDATE users SET failed_logins = %s WHERE id = %s", [failed, u["id"]])
            error = bad
        else:
            conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", [u["id"]])
    if error:
        raise error
    return {k: u[k] for k in ("email", "name", "role", "session_version")} | {"id": str(u["id"])}


def user_for_token(conn, token: str):
    parsed = parse_token(token)
    if not parsed:
        return None
    u = conn.execute("SELECT id, email, name, role, session_version, disabled FROM users WHERE id = %s", [parsed[0]]).fetchone()
    if not u or u["disabled"] or u["session_version"] != parsed[1]:
        return None
    return {"id": str(u["id"]), "email": u["email"], "name": u["name"], "role": u["role"], "session_version": u["session_version"]}


def change_password(conn, user_id: str, current: str, new: str):
    with conn.transaction():
        u = conn.execute("SELECT password_hash FROM users WHERE id = %s FOR UPDATE", [user_id]).fetchone()
        if not u or not verify_password(current, u["password_hash"]):
            raise AccountError("Current password is wrong")
        conn.execute("UPDATE users SET password_hash = %s, session_version = session_version + 1 WHERE id = %s",
                     [hash_password(new), user_id])


def sign_out_everywhere(conn, user_id: str):
    with conn.transaction():
        conn.execute("UPDATE users SET session_version = session_version + 1 WHERE id = %s", [user_id])


def delete_account(conn, user_id: str, password: str):
    """Deletes the user and (ON DELETE CASCADE) all of their data."""
    with conn.transaction():
        u = conn.execute("SELECT password_hash FROM users WHERE id = %s FOR UPDATE", [user_id]).fetchone()
        if not u or not verify_password(password, u["password_hash"]):
            raise AccountError("Password is wrong")
        conn.execute("DELETE FROM users WHERE id = %s", [user_id])
