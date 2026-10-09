"""Per-user secrets (currently: the SerpApi key), encrypted at rest and never sent to the browser.

Encryption: Fernet (AES-128-CBC + HMAC-SHA256) with SECRETS_KEY from the server environment. Stored in the
user's "_secrets" document (Postgres user_docs row protected by row-level security, or a hidden sheet tab in
single-user mode). Only a masked hint ("…a1b2") is ever returned to the dashboard.

Key choice for a run: the user's own saved key; otherwise the server's SERPAPI_KEY, but in multi-user mode
only for admins (so one user's searches never silently spend another account's quota). Keys are changed by
the user; the app never rotates keys by itself."""
import hashlib
import os
import re

DOC = "_secrets"
_KEY_FORMAT = re.compile(r"^[A-Za-z0-9]{20,128}$")


class SecretsError(ValueError):
    pass


def _fernet():
    from cryptography.fernet import Fernet
    k = os.environ.get("SECRETS_KEY", "")
    if not k:
        raise SecretsError("SECRETS_KEY is not set on the server (generate one with: "
                           "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")")
    try:
        return Fernet(k.encode())
    except (ValueError, TypeError):
        raise SecretsError("SECRETS_KEY is not a valid Fernet key") from None


def fingerprint(key: str) -> str:
    """Non-reversible id for usage accounting (never the key itself)."""
    return hashlib.sha256(key.encode()).hexdigest()[:12] if key else "none"


def save_serpapi_key(st, key: str):
    key = (key or "").strip()
    if not _KEY_FORMAT.match(key):
        raise SecretsError("That doesn't look like a SerpApi key (letters and digits only)")
    doc = st.get_json(DOC) or {}
    doc["serpapi"] = _fernet().encrypt(key.encode()).decode()
    doc["serpapi_hint"] = "…" + key[-4:]
    st.put_json(DOC, doc)


def remove_serpapi_key(st):
    doc = st.get_json(DOC) or {}
    doc.pop("serpapi", None)
    doc.pop("serpapi_hint", None)
    st.put_json(DOC, doc)


def get_serpapi_key(st) -> str:
    doc = st.get_json(DOC) or {}
    if not doc.get("serpapi"):
        return ""
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(doc["serpapi"].encode()).decode()
    except InvalidToken:
        raise SecretsError("Your saved SerpApi key can't be decrypted (SECRETS_KEY changed?). Save it again in Settings.") from None


def hint(st) -> str:
    return (st.get_json(DOC) or {}).get("serpapi_hint", "")


def key_for_run(st, multi_user: bool, is_admin: bool) -> tuple:
    """(key, source) where source is "own" | "server" | "none"."""
    own = get_serpapi_key(st) if st is not None else ""
    if own:
        return own, "own"
    server = os.environ.get("SERPAPI_KEY", "").strip()
    if server and (not multi_user or is_admin):
        return server, "server"
    return "", "none"
