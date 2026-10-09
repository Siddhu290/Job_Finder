"""Multiple resume profiles, stored as one JSON document in the hidden _profile tab.

{"use_in_search": bool, "active": "<id>", "profiles": [{"id", "name", "created", "updated", ...clean_profile fields}]}
The resume documents themselves are never stored server-side; only these extracted, user-editable fields."""
import uuid
from datetime import datetime

import llm

MAX_PROFILES = 10


def load(raw) -> dict:
    raw = raw or {}
    if "profiles" in raw:
        return {"use_in_search": bool(raw.get("use_in_search")), "active": raw.get("active", ""),
                "profiles": [p for p in raw["profiles"] if isinstance(p, dict) and p.get("id")]}
    if raw.get("roles"):  # single profile saved by the earlier version
        p = {**llm.clean_profile(raw), "id": "p1", "name": "Resume 1", "created": "", "updated": ""}
        return {"use_in_search": bool(raw.get("active", True)), "active": "p1", "profiles": [p]}
    return {"use_in_search": False, "active": "", "profiles": []}


def active(c) -> dict | None:
    return next((p for p in c["profiles"] if p["id"] == c["active"]), None)


def _stamp():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def add(c, profile: dict, name: str = "") -> dict:
    if len(c["profiles"]) >= MAX_PROFILES:
        raise ValueError(f"At most {MAX_PROFILES} resume profiles; delete one first")
    p = {**llm.clean_profile(profile), "id": uuid.uuid4().hex[:8], "name": _name(name) or f"Resume {len(c['profiles']) + 1}",
         "created": _stamp(), "updated": _stamp()}
    c["profiles"].append(p)
    c["active"] = p["id"]
    c["use_in_search"] = True
    return p


def update(c, pid: str, fields: dict) -> dict:
    p = next((x for x in c["profiles"] if x["id"] == pid), None)
    if not p:
        raise KeyError(pid)
    cleaned = llm.clean_profile({**p, **fields})
    p.update(cleaned, name=_name(fields.get("name")) or p["name"], updated=_stamp())
    return p


def delete(c, pid: str):
    c["profiles"] = [p for p in c["profiles"] if p["id"] != pid]
    if c["active"] == pid:
        c["active"] = c["profiles"][0]["id"] if c["profiles"] else ""
        c["use_in_search"] = c["use_in_search"] and bool(c["profiles"])


def _name(n):
    n = " ".join(str(n or "").split())[:60]
    return n if all(ch not in n for ch in "<>{}") else ""


def search_args(c) -> list:
    """CLI arguments for the active profile when 'use in searches' is on."""
    p = active(c)
    if not c.get("use_in_search") or not p or not p.get("roles"):
        return []
    return ["--roles", ";".join(p["roles"]), "--skills", ";".join(llm.all_skills(p)),
            "--max-years", str(max(1, p.get("experience_years", 0)))]
