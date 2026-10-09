"""Explainable job <-> resume matching. Relevance only: link authenticity is the verification subsystem's job.

Each component is scored 0..1 (or None when the job gives no information, in which case its weight is
dropped and the rest are re-normalised). Weights, out of 100:

    required skills 40 · experience 20 · role title 15 · location/work mode 10 · preferred skills 10 · education 5

Mandatory conditions: an experience requirement above the candidate's level, or a location/work mode the
candidate did not ask for, makes the job "not eligible" and caps the overall score at 25, however well
the skills match. Nothing about the candidate is inferred beyond the (user-editable) profile."""
import re

import filters

WEIGHTS = {"required_skills": 40, "experience": 20, "title": 15, "location": 10, "preferred_skills": 10, "education": 5}
INELIGIBLE_CAP = 25

# canonical skill -> pattern (word-bounded, case-insensitive)
SKILLS = {
    "SQL": r"sql", "Python": r"python", "R": r"r(?=\s*(?:programming|language|studio|,|/|\)))|rstudio", "Excel": r"(?:ms[\s-]?|advanced\s+)?excel",
    "Power BI": r"power\s?bi", "Tableau": r"tableau", "Looker": r"looker(?:\s+studio)?", "Qlik": r"qlik(?:view|\s?sense)?",
    "Pandas": r"pandas", "NumPy": r"numpy", "Scikit-learn": r"scikit[\s-]?learn|sklearn", "Statistics": r"statistic(?:s|al)",
    "Machine Learning": r"machine\s+learning|\bml\b", "Data Visualization": r"data\s+visuali[sz]ation", "Data Cleaning": r"data\s+cleaning|data\s+wrangling",
    "ETL": r"etl|elt", "Data Modeling": r"data\s+model(?:l)?ing", "Data Warehousing": r"data\s+warehous(?:e|ing)",
    "Spark": r"(?:apache\s+)?spark|pyspark", "Hadoop": r"hadoop|hive|hdfs", "Kafka": r"kafka", "Airflow": r"airflow",
    "dbt": r"dbt", "Databricks": r"databricks", "Snowflake": r"snowflake", "BigQuery": r"big\s?query", "Redshift": r"redshift",
    "AWS": r"aws|amazon\s+web\s+services", "Azure": r"azure", "GCP": r"gcp|google\s+cloud", "Docker": r"docker", "Kubernetes": r"kubernetes|k8s",
    "Git": r"git(?:hub|lab)?", "Linux": r"linux|unix|shell\s+scripting|bash", "Java": r"java(?!script)", "Scala": r"scala",
    "JavaScript": r"javascript|js", "MySQL": r"mysql", "PostgreSQL": r"postgres(?:ql)?", "MongoDB": r"mongo(?:db)?",
    "Oracle": r"oracle", "SQL Server": r"sql\s+server|mssql|t-sql", "NoSQL": r"nosql", "Google Analytics": r"google\s+analytics|ga4",
    "A/B Testing": r"a/b\s+test(?:ing)?", "Jupyter": r"jupyter", "APIs": r"rest(?:ful)?\s+apis?|apis?", "SAS": r"sas", "SPSS": r"spss",
}
_SKILL_RX = {k: re.compile(rf"(?<![A-Za-z0-9]){v}(?![A-Za-z0-9])", re.I) for k, v in SKILLS.items()}
_PREFERRED = re.compile(r"prefer|nice[\s-]to[\s-]have|good[\s-]to[\s-]have|bonus|\bplus\b|advantage|desirable|familiarity|exposure\s+to", re.I)
_EDU = {"Engineering/B.Tech": r"b\.?\s?tech|b\.?e\b|bachelor\S*\s+of\s+engineering|engineering\s+degree",
        "Computer Science": r"computer\s+science|\bcse\b|\bcs\b", "Statistics/Mathematics": r"statistics|mathematics|maths",
        "BCA/MCA": r"\bbca\b|\bmca\b", "B.Sc/M.Sc": r"b\.?\s?sc|m\.?\s?sc", "MBA": r"\bmba\b", "B.Com": r"b\.?\s?com\b",
        "Any graduate": r"any\s+graduate|bachelor'?s?\s+degree|graduate\s+in\s+any"}
_EDU_RX = {k: re.compile(v, re.I) for k, v in _EDU.items()}


_DEGREE = re.compile(r"degree|bachelor|master'?s|graduat|b\.?\s?tech|b\.?\s?e\b|m\.?\s?tech|diploma|\bphd\b", re.I)


def _sentence(text, m):
    start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    ends = [i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i != -1]
    return text[start:min(ends) if ends else len(text)]


def find_skills(text: str) -> list:
    return [k for k, rx in _SKILL_RX.items() if rx.search(text or "")]


def analyze_job(description: str) -> dict:
    """Required vs preferred skills, minimum years and education asked for, from the job text.
    A skill counts as 'preferred' when a preference phrase precedes it in the same sentence/line."""
    text = description or ""
    required, preferred = [], []
    for name, rx in _SKILL_RX.items():
        # skip mentions inside degree requirements ("degree in Statistics" is education, not a skill)
        hits = [m for m in rx.finditer(text) if not _DEGREE.search(_sentence(text, m))]
        if not hits:
            continue
        pref = all(_PREFERRED.search(re.split(r"[.\n•;]", text[max(0, m.start() - 160):m.start()])[-1]) for m in hits)
        (preferred if pref else required).append(name)
    mins = [lo for lo, _, _ in filters._mentions(text.replace("–", "-"))]
    education = [k for k, rx in _EDU_RX.items() if rx.search(text)]
    return {"required": required, "preferred": preferred, "min_years": min(mins) if mins else None, "education": education}


def profile_skills(profile: dict) -> set:
    keys = ("skills", "programming_languages", "data_tools", "databases", "frameworks")
    have = {s.lower() for k in keys for s in profile.get(k, []) or []}
    # map free-text profile skills onto canonical names so "MS Excel" matches "Excel"
    for name, rx in _SKILL_RX.items():
        if any(rx.fullmatch(s) or rx.search(s) for s in have):
            have.add(name.lower())
    return have


def score(job: dict, analysis: dict, profile: dict, search: "filters.SearchProfile") -> dict:
    """job: {title, location, employment, experience_text, description, status}. Returns the full breakdown."""
    have = profile_skills(profile)
    req, pref = analysis.get("required", []), analysis.get("preferred", [])
    matched = [s for s in req + pref if s.lower() in have]
    missing_req = [s for s in req if s.lower() not in have]
    missing_pref = [s for s in pref if s.lower() not in have]
    comp, why, mandatory_fail = {}, [], []

    comp["required_skills"] = (len(req) - len(missing_req)) / len(req) if req else None
    comp["preferred_skills"] = (len(pref) - len(missing_pref)) / len(pref) if pref else None

    verdict, summary = filters.experience_check(job.get("description", "") or job.get("experience_text", ""), search)
    comp["experience"] = {filters.ELIGIBLE: 1.0, filters.BORDERLINE: 0.5, filters.UNKNOWN: 0.6}.get(verdict, 0.0)
    if verdict == filters.TOO_SENIOR:
        mandatory_fail.append(f"experience: {summary}")
    elif verdict == filters.UNKNOWN:
        why.append("experience requirement not stated")

    wfh = "work from home" in (job.get("employment", "") or "").lower()
    loc_ok, loc_why = filters.location_check(job.get("location", ""), job.get("description", ""), wfh, search)
    comp["location"] = 1.0 if loc_ok else 0.0
    if not loc_ok:
        mandatory_fail.append(f"location: {loc_why}")

    roles = profile.get("roles") or []
    if roles:
        if filters._role_match(job.get("title", ""), roles):
            comp["title"] = 1.0
        else:
            title_words = filters._tokens(job.get("title", "")) - filters._GENERIC
            best = max((len(title_words & (filters._tokens(r) - filters._GENERIC)) / max(1, len(filters._tokens(r) - filters._GENERIC)) for r in roles), default=0)
            comp["title"] = 0.5 if best >= 0.5 else 0.0
    else:
        comp["title"] = 1.0 if filters.RELEVANT_TITLE.search(job.get("title", "")) else 0.0

    edu_have = {k for k, rx in _EDU_RX.items() if any(rx.search(str(e)) for e in profile.get("education", []) or [])}
    edu_need = set(analysis.get("education", []))
    if edu_need:
        comp["education"] = 1.0 if (edu_need & edu_have or "Any graduate" in edu_need and edu_have) else 0.0
        if not comp["education"]:
            why.append("education asked for: " + ", ".join(sorted(edu_need)))
    else:
        comp["education"] = None

    used = {k: v for k, v in comp.items() if v is not None}
    overall = round(100 * sum(WEIGHTS[k] * v for k, v in used.items()) / sum(WEIGHTS[k] for k in used)) if used else 0
    eligible = not mandatory_fail
    if not eligible:
        overall = min(overall, INELIGIBLE_CAP)
    if missing_req:
        why.append("missing required: " + ", ".join(missing_req[:6]))
    if matched:
        why.append("you have: " + ", ".join(matched[:8]))

    verified = job.get("status") == "Verified"
    if not eligible:
        action = "Skip: " + mandatory_fail[0]
    elif len(missing_req) > 2:
        action = f"Low fit: apply only if you can show {', '.join(missing_req[:3])}"
    elif verified and overall >= 70:
        action = "Strong match: apply now via the verified link"
    elif not verified:
        action = "Find this role on the company's own careers site, then apply"
    else:
        action = "Tailor your resume" + (f" for {', '.join(missing_req[:2])}" if missing_req else "") + ", then apply"
    return {"overall": overall, "eligible": eligible, "components": {k: (None if v is None else round(v, 2)) for k, v in comp.items()},
            "weights": WEIGHTS, "matched": matched, "missing_required": missing_req, "missing_preferred": missing_pref,
            "mandatory_failures": mandatory_fail, "reasons": why, "next_action": action}
