"""Google Jobs keyword searches built from the search profile (locations + work mode).
Ordered most-valuable first so a small SerpApi budget still covers the core searches."""

KEYWORDS = ["Data Analyst fresher", "Data Engineer fresher", "Junior Data Analyst", "Junior Data Engineer",
            "Data Analyst trainee", "Graduate Data Engineer", "Associate Data Analyst", "entry level Data Engineer",
            "Graduate Data Analyst", "Data Engineer trainee"]
WFH_KEYWORDS = ["Data Analyst fresher", "Data Engineer fresher", "entry level Data Analyst", "entry level Data Engineer",
                "Data Analyst 0-1 years", "Data Engineer 0-1 years"]


def build(locations, mode="any", roles=()) -> list:
    """[(query, serpapi_location, work_from_home_only)], interleaved so each location and WFH get early slots.
    roles (from the resume) replace the default data analyst/engineer keywords."""
    kws = [f"{r} {lvl}" for lvl in ("fresher", "entry level", "junior") for r in roles] if roles else KEYWORDS
    wfh_kws = [f"{r} {lvl}" for lvl in ("fresher", "entry level") for r in roles] if roles else WFH_KEYWORDS
    per_city = [[(f"{kw} {city}", "India", False) for kw in kws] for city in locations] if mode != "wfh" else []
    wfh = [(f"{kw} work from home", "India", True) for kw in wfh_kws] if mode != "onsite" else []
    lanes = per_city + ([wfh] if wfh else [])
    out = []
    for i in range(max((len(l) for l in lanes), default=0)):
        out += [lane[i] for lane in lanes if i < len(lane)]
    return list(dict.fromkeys(out))  # never spend two searches on the same query
