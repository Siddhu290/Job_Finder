"""Access to the admin's API keys (SerpApi + Groq) for users without their own.

A user asks (status "pending"); every admin sees the request in the Admin section (in-app notification) and
approves or denies it. Approved users' searches and AI calls may use the server keys; an admin can revoke at
any time. Admins always may. All decisions are recorded (who, when)."""
import re

STATUSES = ("none", "pending", "approved", "denied")


class AccessError(ValueError):
    pass


def may_use_server_keys(user: dict | None) -> bool:
    return bool(user) and (user.get("role") == "admin" or user.get("shared_access") == "approved")


def status(conn, user_id) -> dict:
    r = conn.execute("SELECT shared_access, shared_access_message, shared_access_requested_at, shared_access_decided_at "
                     "FROM users WHERE id = %s", [user_id]).fetchone()
    if not r:
        return {"status": "none"}
    return {"status": r["shared_access"], "message": r["shared_access_message"],
            "requested_at": r["shared_access_requested_at"].isoformat() if r["shared_access_requested_at"] else "",
            "decided_at": r["shared_access_decided_at"].isoformat() if r["shared_access_decided_at"] else ""}


def request(conn, user: dict, message: str = "") -> dict:
    if user.get("role") == "admin":
        raise AccessError("Admins already use the server keys")
    msg = re.sub(r"\s+", " ", str(message or "")).strip()[:300]
    with conn.transaction():
        conn.execute("UPDATE users SET shared_access = 'pending', shared_access_message = %s, shared_access_requested_at = now() "
                     "WHERE id = %s AND shared_access <> 'approved'", [msg, user["id"]])
    return status(conn, user["id"])


def _require_admin(admin):
    if not admin or admin.get("role") != "admin":
        raise PermissionError("Only an admin can do this")


def decide(conn, admin: dict, target_id: str, approve: bool) -> dict:
    _require_admin(admin)
    with conn.transaction():
        n = conn.execute("UPDATE users SET shared_access = %s, shared_access_decided_at = now(), shared_access_decided_by = %s "
                         "WHERE id = %s AND role <> 'admin'", ["approved" if approve else "denied", admin["email"], target_id]).rowcount
    if not n:
        raise AccessError("No such user")
    return status(conn, target_id)


def revoke(conn, admin: dict, target_id: str) -> dict:
    _require_admin(admin)
    with conn.transaction():
        conn.execute("UPDATE users SET shared_access = 'none', shared_access_decided_at = now(), shared_access_decided_by = %s "
                     "WHERE id = %s AND role <> 'admin'", [admin["email"], target_id])
    return status(conn, target_id)


def overview(conn, admin: dict) -> dict:
    """Admin view: pending requests (the notifications), approved users, and all accounts."""
    _require_admin(admin)
    rows = conn.execute("SELECT id, email, username, name, role, disabled, created_at, last_run_at, shared_access, shared_access_message, "
                        "shared_access_requested_at, shared_access_decided_at, shared_access_decided_by FROM users ORDER BY created_at").fetchall()
    fmt = lambda d: d.strftime("%Y-%m-%d %H:%M") if d else ""
    users = [{"id": str(r["id"]), "email": r["email"], "username": r["username"] or "", "name": r["name"], "role": r["role"],
              "disabled": r["disabled"], "created": fmt(r["created_at"]), "last_search": fmt(r["last_run_at"]),
              "access": r["shared_access"], "message": r["shared_access_message"], "requested": fmt(r["shared_access_requested_at"]),
              "decided": fmt(r["shared_access_decided_at"]), "decided_by": r["shared_access_decided_by"]} for r in rows]
    return {"pending": [u for u in users if u["access"] == "pending"], "approved": [u for u in users if u["access"] == "approved"],
            "users": users}


def pending_count(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM users WHERE shared_access = 'pending'").fetchone()["n"]
