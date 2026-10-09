"""The user's resume collection: every upload, pasted version and approved tailored draft, each with its own name.

Stored per user (Postgres rows protected by row-level security, or hidden tabs in single-user mode), and the text
is encrypted with SECRETS_KEY. An index document ("_resumes") holds names/metadata; each version's encrypted text
lives in its own document ("_resume_<id>"). Nothing is ever sent to employers."""
import re
import uuid
from datetime import datetime

import user_secrets

INDEX = "_resumes"
MAX_VERSIONS = 20
MAX_CHARS = 25_000          # keeps an encrypted version under the 50k-character Google Sheets cell limit
SOURCES = {"upload", "pasted", "tailored", "edited"}


class ResumeError(ValueError):
    pass


def _name(n):
    n = " ".join(str(n or "").split())[:80]
    if not n or re.search(r"[<>{}]", n):
        raise ResumeError("Give the resume a plain name (up to 80 characters)")
    return n


def _index(st) -> list:
    return (st.get_json(INDEX) or {}).get("versions", [])


def list_versions(st) -> list:
    return sorted(_index(st), key=lambda v: v.get("created", ""), reverse=True)


def save(st, name: str, text: str, source: str = "pasted", job: str = "") -> dict:
    text = (text or "").strip()
    if len(text) < 100:
        raise ResumeError("The resume text is too short")
    versions = _index(st)
    if len(versions) >= MAX_VERSIONS:
        raise ResumeError(f"You can keep up to {MAX_VERSIONS} resumes; delete one first")
    name = _name(name)
    if any(v["name"].lower() == name.lower() for v in versions):
        name = f"{name} ({datetime.now().strftime('%d %b %H:%M')})"
    v = {"id": uuid.uuid4().hex[:10], "name": name, "source": source if source in SOURCES else "pasted",
         "job": str(job or "")[:120], "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
         "chars": min(len(text), MAX_CHARS)}
    st.put_json(f"_resume_{v['id']}", {"text": user_secrets.encrypt_text(text[:MAX_CHARS])})
    st.put_json(INDEX, {"versions": versions + [v]})
    return v


def get_text(st, vid: str) -> str:
    if not any(v["id"] == vid for v in _index(st)):
        raise KeyError(vid)
    return user_secrets.decrypt_text((st.get_json(f"_resume_{vid}") or {}).get("text", ""))


def rename(st, vid: str, name: str) -> dict:
    versions = _index(st)
    v = next((x for x in versions if x["id"] == vid), None)
    if not v:
        raise KeyError(vid)
    v["name"] = _name(name)
    st.put_json(INDEX, {"versions": versions})
    return v


def delete(st, vid: str):
    versions = _index(st)
    if not any(v["id"] == vid for v in versions):
        raise KeyError(vid)
    st.put_json(f"_resume_{vid}", {})        # remove the text first
    st.put_json(INDEX, {"versions": [v for v in versions if v["id"] != vid]})
