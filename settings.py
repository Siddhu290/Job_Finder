"""User settings (hidden _settings tab, JSON). Used by the dashboard and by scheduled runs, so the cron
searches exactly what the user configured. Every value is validated; unknown keys are dropped."""
import re

import filters

DEFAULTS = {
    "roles": ["Data Analyst", "Data Engineer"],
    "locations": list(filters.DEFAULT_LOCATIONS),
    "mode": "any",
    "max_age_days": 7,
    "employment_types": ["full-time", "graduate program"],
    "exclude": [],
    "prefer": [],
    "follow_up_days": 5,
    "sheet_mirror": True,      # multi-user: copy my jobs to my tab in the admin's Google spreadsheet
}
_PLACE = re.compile(r"^[A-Za-z][A-Za-z .\-]{0,39}$")
_ROLE = re.compile(r"^[A-Za-z][A-Za-z0-9 +#./&()-]{1,59}$")
_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&+#'-]{0,59}$")


def clean(raw: dict) -> dict:
    raw = raw or {}
    out = dict(DEFAULTS)
    roles = [str(r).strip() for r in raw.get("roles", out["roles"]) or [] if _ROLE.match(str(r).strip())][:6]
    out["roles"] = roles or list(DEFAULTS["roles"])
    locs = [str(l).strip() for l in raw.get("locations", out["locations"]) or [] if _PLACE.match(str(l).strip())][:8]
    out["locations"] = locs or list(DEFAULTS["locations"])
    out["mode"] = raw.get("mode") if raw.get("mode") in filters.MODES else "any"
    out["max_age_days"] = raw.get("max_age_days") if raw.get("max_age_days") in (1, 3, 7, 14, 30) else 7
    out["employment_types"] = [e for e in raw.get("employment_types", out["employment_types"]) or [] if e in filters.EMPLOYMENT_TYPES]
    out["exclude"] = [str(k).strip() for k in raw.get("exclude", []) or [] if _WORD.match(str(k).strip())][:30]
    out["prefer"] = [str(k).strip() for k in raw.get("prefer", []) or [] if _WORD.match(str(k).strip())][:30]
    out["sheet_mirror"] = raw.get("sheet_mirror", True) is not False
    try:
        out["follow_up_days"] = min(max(int(raw.get("follow_up_days", 5)), 1), 30)
    except (TypeError, ValueError):
        out["follow_up_days"] = 5
    return out


def run_args(s: dict) -> list:
    """CLI arguments for a run with these settings."""
    args = ["--locations", ";".join(s["locations"]), "--mode", s["mode"], "--max-age-days", str(s["max_age_days"])]
    if s["roles"] != DEFAULTS["roles"]:
        args += ["--roles", ";".join(s["roles"])]
    if s["employment_types"]:
        args += ["--employment", ";".join(s["employment_types"])]
    if s["exclude"]:
        args += ["--exclude", ";".join(s["exclude"])]
    if s["prefer"]:
        args += ["--prefer", ";".join(s["prefer"])]
    return args


def search_profile(s: dict, profile: dict | None = None) -> "filters.SearchProfile":
    """SearchProfile for scoring on the dashboard (same rules as the runs)."""
    return filters.SearchProfile(s["locations"], s["mode"], (profile or {}).get("roles", []), (),
                                 max(1, (profile or {}).get("experience_years", 0)), s["max_age_days"],
                                 s["employment_types"], s["exclude"], s["prefer"])
