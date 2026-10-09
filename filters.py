"""Role, experience, location and freshness rules. Pure functions, no I/O."""
import re
from datetime import date, datetime, timedelta, timezone

# ---------- title ----------
RELEVANT_TITLE = re.compile(
    r"\bdata\s+(analyst|engineer)\b|\banalytics\s+engineer\b|\b(bi|business\s+intelligence)\s+analyst\b"
    r"|\bdata\s+analytics\s+(analyst|associate|trainee|engineer|graduate)\b"
    r"|\banalytics\s+(trainee|associate|graduate|analyst)\b", re.I)
_SENIOR = re.compile(
    r"\b(senior|sr|snr|lead|principal|staff|manager|mgr|head|director|architect|vp|chief)\b"
    r"|\b(ii|iii|iv)\b|\b(level|l)\s*[2-9]\b|\b[2-9]\s*$", re.I)
_INTERN = re.compile(r"\bintern(ship)?\b", re.I)


_GENERIC = {"junior", "jr", "associate", "assoc", "graduate", "grad", "trainee", "entry", "level", "fresher", "freshers",
            "i", "1", "the", "of", "and", "a", "an", "role", "position"}


def _tokens(text):
    return set(re.findall(r"[a-z0-9+#.]+", (text or "").lower().replace("&", " and "))) - {"-"}


def _role_match(title, roles):
    """True if every meaningful word of some resume role appears in the title ('Business Analyst' ~ 'Junior Business Analyst - Pune')."""
    words = _tokens(title)
    return any((need := _tokens(r) - _GENERIC) and need <= words for r in roles)


def title_check(title: str):
    t = title or ""
    roles = PROFILE.roles
    if roles and not _role_match(t, roles):
        return False, "title doesn't match the roles from your resume"
    if not roles and not RELEVANT_TITLE.search(t):
        return False, "title not a data analyst/engineer role"
    if _INTERN.search(t) and "internship" not in PROFILE.employment_types:
        return False, "internship (not selected in employment types)"
    bad = next((k for k in PROFILE.exclude if re.search(rf"\b{re.escape(k)}\b", t, re.I)), None)
    if bad:
        return False, f"excluded keyword '{bad}'"
    if _SENIOR.search(t):
        return False, "title indicates a senior/experienced level"
    return True, "relevant title"


# ---------- experience ----------
ELIGIBLE, TOO_SENIOR, BORDERLINE, UNKNOWN = "eligible", "too_senior", "borderline", "unknown"
_NUM = r"(\d{1,2}(?:\.\d)?)"
_YEARS = r"\s*(?:\+\s*)?(years?|yrs?|months?)"
_EXP_RANGE = re.compile(_NUM + r"\s*(?:-|to)\s*" + _NUM + _YEARS, re.I)
_EXP_SINGLE = re.compile(_NUM + r"\s*(\+)?" + _YEARS, re.I)
_FRESHER_POS = re.compile(
    r"\bfreshers?\b|\bno\s+(prior\s+)?(work\s+)?experience\s+(is\s+)?required\b|\bentry[\s-]level\b"
    r"|\brecent\s+(graduates?|grads?)\b|\bnew\s+grads?\b|\bgraduate\s+(program+e?|trainee|scheme)\b"
    r"|\b20(2[4-7])\s+(batch|graduates?|pass[\s-]?outs?)\b|\bcampus\s+(hire|hiring|recruit\w*)\b", re.I)
_FRESHER_NEG = re.compile(r"\bfreshers?\s+(need\s+not|should\s+not|cannot|can\s*not|are\s+not|not\s+eligible|please\s+do\s+not)", re.I)


def _mentions(text):
    """Yield (min_years, max_years, snippet) for numeric experience requirements near the word 'experience'."""
    taken = []
    for rx, is_range in ((_EXP_RANGE, True), (_EXP_SINGLE, False)):
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            window = text[max(0, m.start() - 70): m.end() + 70].lower()
            if "experien" not in window and not re.search(r"\bexp\b", window):
                continue
            taken.append((m.start(), m.end()))
            unit = m.groups()[-1].lower()
            scale = 1 / 12 if unit.startswith("month") else 1
            lo = float(m.group(1)) * scale
            hi = float(m.group(2)) * scale if is_range else None
            yield lo, hi, m.group(0)


def experience_check(text: str, profile=None):
    """Returns (verdict, summary). Never infers eligibility from job title words alone."""
    text = (text or "").replace("–", "-").replace("—", "-")
    if _FRESHER_NEG.search(text):
        return TOO_SENIOR, "states freshers are not eligible"
    mentions = list(_mentions(text))
    mins = [lo for lo, _, _ in mentions]
    limit = (profile or PROFILE).max_years  # 1 for freshers; more if the resume shows experience
    if mins and min(mins) > limit:
        return TOO_SENIOR, f"requires {mentions[mins.index(min(mins))][2].strip()} experience"
    if mins and 1 <= min(mins) <= limit and limit > 1:
        return ELIGIBLE, f"{mentions[mins.index(min(mins))][2].strip()} (within your {limit:g} years)"
    if any(lo < 1 for lo in mins):
        lo_m = next(s for lo, _, s in mentions if lo < 1)
        hi = max((h for lo, h, _ in mentions if lo < 1 and h is not None), default=None)
        if hi is not None and hi > 1:
            # "0-3 years" is open to freshers but signals preference for experience
            return ELIGIBLE, f"{lo_m.strip()} (accepts 0 years)"
        return ELIGIBLE, lo_m.strip()
    if mins and min(mins) == 1:
        return BORDERLINE, "requires 1 year of experience"
    m = _FRESHER_POS.search(text)
    if m:
        return ELIGIBLE, f"Fresher/entry-level ('{m.group(0)}')"
    return UNKNOWN, "experience requirement not stated"


# ---------- location ----------
INDIA_PLACES = (
    "india", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "chennai", "delhi", "new delhi", "gurgaon",
    "gurugram", "noida", "kolkata", "ahmedabad", "jaipur", "kochi", "cochin", "chandigarh", "indore", "coimbatore",
    "thiruvananthapuram", "trivandrum", "mysore", "mysuru", "nagpur", "bhubaneswar", "vadodara", "lucknow",
    "visakhapatnam", "vizag", "navi mumbai", "thane", "mohali", "surat", "goa", "karnataka", "maharashtra",
    "telangana", "tamil nadu", "haryana", "uttar pradesh", "west bengal", "gujarat", "kerala", "rajasthan",
    "andhra pradesh", "odisha", "madhya pradesh", "punjab", "keralam", "assam", "bihar", "jharkhand",
    "chhattisgarh", "uttarakhand", "himachal pradesh", "jammu and kashmir", "jammu", "ladakh", "tripura", "meghalaya",
    "manipur", "mizoram", "nagaland", "sikkim", "arunachal pradesh", "puducherry", "pondicherry", "orissa",
    "guwahati", "patna", "ranchi", "raipur", "dehradun", "bhopal", "nashik", "aurangabad", "madurai", "tiruchirappalli",
    "trichy", "vijayawada", "warangal", "mangaluru", "mangalore", "hubli", "belagavi", "kozhikode", "thrissur",
    "ludhiana", "amritsar", "jalandhar", "kanpur", "varanasi", "prayagraj", "agra", "meerut", "ghaziabad",
    "faridabad", "rajkot", "udaipur", "jodhpur", "salem", "tiruppur", "vellore", "gandhinagar", "secunderabad",
    "greater noida", "jamshedpur", "dhanbad", "siliguri", "durgapur", "shimla", "srinagar", "panaji", "tirupati",
)
_INDIA_RX = re.compile(r"\b(" + "|".join(re.escape(p) for p in INDIA_PLACES) + r")\b", re.I)
_REMOTE_RX = re.compile(r"\b(remote|anywhere|work\s+from\s+home|wfh|worldwide|global)\b", re.I)
_INDIA_REMOTE_OK = re.compile(
    r"\b(remote|work\s+from\s+home|wfh|distributed)\b[^.\n]{0,80}\bindia\b"
    r"|\bindia\b[^.\n]{0,60}\b(remote|work\s+from\s+home|wfh)\b"
    r"|\b(based|located|resid\w*|living|candidates|applicants|hiring)\s+(in|from|across)\s+(anywhere\s+in\s+)?india\b", re.I)
_FOREIGN_ONLY = re.compile(
    r"\b(must|should|need\s+to)\s+(be\s+)?(located|based|resid\w*|living)\s+(in|within)\s+(the\s+)?"
    r"(us|usa|u\.s\.|united\s+states|uk|united\s+kingdom|canada|europe|eu|australia|emea|latam|north\s+america)\b"
    r"|\b(us|usa|uk|eu|canada)[\s-]only\b|\bauthori[sz]ed\s+to\s+work\s+in\s+the\s+(us|united\s+states)\b", re.I)


# Known city aliases/localities, so "Bangalore" also matches "Whitefield, Bengaluru".
CITY_ALIASES = {
    "Pune": r"pune|pimpri|chinchwad|pcmc|hinjewadi|hinjawadi|kharadi|magarpatta|hadapsar|baner|wakad|viman\s+nagar|"
            r"yerawada|yerwada|kalyani\s+nagar|aundh|balewadi|talawade|shivajinagar",
    "Bengaluru": r"bengaluru|bangalore|whitefield|electronic\s+city|koramangala|hsr\s+layout|marathahalli|bellandur|"
                 r"indiranagar|manyata|outer\s+ring\s+road|yeshwanthpur|jp\s+nagar|hebbal",
    "Nashik": r"nashik|nasik",
    "Mumbai": r"mumbai|bombay|navi\s+mumbai|thane|powai|andheri|bandra|goregaon|malad|vikhroli",
    "Delhi NCR": r"delhi|new\s+delhi|ncr|gurgaon|gurugram|noida|greater\s+noida|ghaziabad|faridabad",
    "Hyderabad": r"hyderabad|secunderabad|hitech\s+city|gachibowli|madhapur",
    "Chennai": r"chennai|madras|guindy|sholinganallur|siruseri",
    "Kolkata": r"kolkata|calcutta|salt\s+lake",
    "Kochi": r"kochi|cochin|kakkanad",
    "Thiruvananthapuram": r"thiruvananthapuram|trivandrum|technopark",
}
DEFAULT_LOCATIONS = ("Pune", "Bengaluru", "Nashik")
MODES = ("any", "wfh", "onsite")  # any work mode / work from home only / office or hybrid only


class SearchProfile:
    """Which locations and work modes a run accepts. Office/hybrid jobs must be in one of the locations;
    work-from-home jobs may be anywhere in India (if open to India-based applicants)."""

    def __init__(self, locations=DEFAULT_LOCATIONS, mode="any", roles=(), skills=(), max_years=1,
                 max_age_days=None, employment_types=(), exclude=(), prefer=()):
        self.locations = [l.strip() for l in locations if l and l.strip()] or list(DEFAULT_LOCATIONS)
        self.mode = mode if mode in MODES else "any"
        self.roles = [r.strip() for r in roles if r and r.strip()]      # from the resume; empty = data analyst/engineer
        self.skills = [k.strip().lower() for k in skills if k and k.strip()]
        self.max_years = max(1.0, float(max_years or 1))
        self.max_age_days = max_age_days                                    # None = JOB_MAX_AGE_DAYS from config
        self.employment_types = [e.lower() for e in employment_types if e]  # empty = any type except internships
        self.exclude = [k.strip() for k in exclude if k and k.strip()]      # keywords that disqualify a title/company
        self.prefer = [c.strip() for c in prefer if c and c.strip()]        # companies ranked higher
        self._rx = {}
        for name in self.locations:
            key = next((k for k, rx in CITY_ALIASES.items() if re.fullmatch(rf"({rx})", name, re.I)), None)
            self._rx[key or name.title()] = re.compile(rf"\b({CITY_ALIASES[key] if key else re.escape(name)})\b", re.I)

    def city(self, location: str) -> str:
        return next((c for c, rx in self._rx.items() if rx.search(location or "")), "")


PROFILE = SearchProfile()


def set_profile(locations=DEFAULT_LOCATIONS, mode="any", roles=(), skills=(), max_years=1, **settings):
    global PROFILE
    PROFILE = SearchProfile(locations, mode, roles, skills, max_years, **settings)
    return PROFILE


def office_city(location: str) -> str:
    """Name of the searched location this job is in, else ''."""
    return PROFILE.city(location)


_OFFICE_RX = re.compile(r"\b(hybrid|on-?site|in[\s-]office|work\s+from\s+office|wfo)\b", re.I)
_REMOTE_JOB_DESC = re.compile(
    r"\b(fully|100%|completely|permanent(ly)?)\s+remote\b|\bremote\s+(role|position|job|opportunity|work(ing)?|first|only)\b"
    r"|\bwork[\s-]+from[\s-]+home\b|\bwfh\b", re.I)


def is_remote_job(location: str, description: str = "", remote: bool = False) -> bool:
    if _OFFICE_RX.search(location or ""):
        return False
    return bool(remote or _REMOTE_RX.search(location or "") or _REMOTE_JOB_DESC.search(description or ""))


def location_check(location: str, description: str = "", remote: bool = False, profile=None):
    """Per the active SearchProfile: office/hybrid jobs in a searched location (unless mode is 'wfh');
    work-from-home jobs open to India-based applicants (unless mode is 'onsite')."""
    loc, p = location or "", profile or PROFILE
    wfh = is_remote_job(loc, description, remote)
    city = p.city(loc)
    if city and (p.mode != "wfh" or wfh):
        return True, city
    if not wfh or p.mode == "onsite":
        where = "/".join(p.locations)
        if p.mode == "wfh":
            return False, "not work-from-home"
        if _INDIA_RX.search(loc) or city:
            return False, f"outside {where}" + ("" if p.mode == "onsite" else " and not work-from-home") + f" ({loc})"
        return False, f"location outside India ({loc})" if loc.strip() else "location not stated"
    if _FOREIGN_ONLY.search(description or ""):
        return False, "remote but restricted to applicants outside India"
    if _INDIA_RX.search(loc) or _INDIA_REMOTE_OK.search(description or ""):
        return True, "work from home, open to India-based applicants"
    return False, "remote without explicit India eligibility"


EMPLOYMENT_TYPES = {"full-time": r"full[\s-]?time|permanent|regular", "internship": r"intern",
                    "contract": r"contract|temporary|freelance", "part-time": r"part[\s-]?time",
                    "graduate program": r"graduate\s+(program|scheme)|trainee|campus"}


def employment_check(employment_type: str, title: str = ""):
    """Selected employment types only. Unknown types pass (verification/experience rules still apply)."""
    if not PROFILE.employment_types:
        return True, "any employment type"
    text = f"{employment_type} {title}"
    found = [k for k, rx in EMPLOYMENT_TYPES.items() if re.search(rx, text, re.I)]
    if not found:
        return True, "employment type not stated"
    ok = [k for k in found if k in PROFILE.employment_types]
    return (True, ok[0]) if ok else (False, f"employment type {found[0]} not selected")


_FRESHER_TITLE = re.compile(r"\b(fresher|freshers|entry[\s-]level|graduate|trainee|junior|jr)\b", re.I)


def contradiction(title: str, verdict: str, summary: str) -> str:
    """'' or a message when the title promises an entry-level role but the description asks for more."""
    m = _FRESHER_TITLE.search(title or "")
    return f"contradictory listing: title says '{m.group(0)}' but description {summary}" if m and verdict == TOO_SENIOR else ""


def skill_match(text: str) -> tuple:
    """(matched_skills, total) of resume skills mentioned in the job text."""
    words = " " + re.sub(r"[^a-z0-9+#.]+", " ", (text or "").lower()) + " "
    hits = [k for k in PROFILE.skills if f" {re.sub(r'[^a-z0-9+#.]+', ' ', k).strip()} " in words]
    return hits, len(PROFILE.skills)


# ---------- freshness ----------
_REL = re.compile(r"(\d+)\+?\s*(minute|hour|day|week|month)s?\s+ago", re.I)


def parse_posted(value, today: date | None = None) -> date | None:
    """Accepts '3 days ago', 'Posted 30+ Days Ago', 'today', ISO strings, epoch millis."""
    today = today or date.today()
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc).date()
    s = str(value).strip().lower()
    if "today" in s or "just" in s or re.search(r"\b(minute|hour)s?\s+ago", s):
        return today
    if "yesterday" in s:
        return today - timedelta(days=1)
    m = _REL.search(s)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"day": n, "week": 7 * n, "month": 30 * n}.get(unit, 0)
        return today - timedelta(days=days)
    try:
        return datetime.fromisoformat(s.replace("z", "+00:00")).date()
    except ValueError:
        return None


def is_fresh(posted: date | None, max_age_days: int, today: date | None = None) -> bool:
    return posted is None or (today or date.today()) - posted <= timedelta(days=max_age_days)
