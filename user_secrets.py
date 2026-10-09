"""Per-user secrets (the SerpApi key and the Groq AI key), encrypted at rest and never sent to the browser.

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
KINDS = {
    "serpapi": {"env": ("SERPAPI_KEY",), "format": re.compile(r"^[A-Za-z0-9]{20,128}$"),
                "bad": "That doesn't look like a SerpApi key (letters and digits only)"},
    "groq": {"env": ("LLM_API_KEY", "GROQ_API_KEY"), "format": re.compile(r"^gsk_[A-Za-z0-9]{20,120}$"),
             "bad": "That doesn't look like a Groq key (it starts with gsk_)"},
}


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


def save_key(st, kind: str, key: str):
    key = (key or "").strip()
    if not KINDS[kind]["format"].match(key):
        raise SecretsError(KINDS[kind]["bad"])
    doc = st.get_json(DOC) or {}
    doc[kind] = _fernet().encrypt(key.encode()).decode()
    doc[kind + "_hint"] = "…" + key[-4:]
    st.put_json(DOC, doc)


def remove_key(st, kind: str):
    doc = st.get_json(DOC) or {}
    doc.pop(kind, None)
    doc.pop(kind + "_hint", None)
    st.put_json(DOC, doc)


def get_key(st, kind: str) -> str:
    doc = st.get_json(DOC) or {}
    if not doc.get(kind):
        return ""
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(doc[kind].encode()).decode()
    except InvalidToken:
        raise SecretsError(f"Your saved {kind} key can't be decrypted (SECRETS_KEY changed?). Save it again in Settings.") from None


def key_hint(st, kind: str) -> str:
    return (st.get_json(DOC) or {}).get(kind + "_hint", "")


def key_for(st, kind: str, multi_user: bool, is_admin: bool) -> tuple:
    """(key, source) where source is "own" | "server" | "none". In multi-user mode the server keys are only for
    users allowed to share them (admins and users an admin approved): pass that as is_admin."""
    own = get_key(st, kind) if st is not None else ""
    if own:
        return own, "own"
    server = next((os.environ[e].strip() for e in KINDS[kind]["env"] if os.environ.get(e, "").strip()), "")
    if server and (not multi_user or is_admin):
        return server, "server"
    return "", "none"


# SerpApi-specific names used elsewhere
save_serpapi_key = lambda st, key: save_key(st, "serpapi", key)          # noqa: E731
remove_serpapi_key = lambda st: remove_key(st, "serpapi")                 # noqa: E731
get_serpapi_key = lambda st: get_key(st, "serpapi")                       # noqa: E731
hint = lambda st: key_hint(st, "serpapi")                                 # noqa: E731
key_for_run = lambda st, multi_user, is_admin: key_for(st, "serpapi", multi_user, is_admin)  # noqa: E731


def encrypt_text(text: str) -> str:
    return _fernet().encrypt((text or "").encode()).decode()


def decrypt_text(token: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt((token or "").encode()).decode()
    except InvalidToken:
        raise SecretsError("This resume can't be decrypted (SECRETS_KEY changed?)") from None
