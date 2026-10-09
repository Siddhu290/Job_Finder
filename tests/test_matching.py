import filters
from matching import INELIGIBLE_CAP, analyze_job, find_skills, score

JD = """We are hiring a Data Analyst (Fresher). Requirements: strong SQL and Python, Excel, Power BI dashboards.
Bachelor's degree in Computer Science or Statistics. 0-1 years of experience.
Nice to have: exposure to Airflow or Snowflake. Good to have: Tableau."""
PROFILE = {"roles": ["Data Analyst"], "skills": ["SQL", "Python", "MS Excel", "Tableau"], "education": ["B.Tech Computer Science 2025"]}
PUNE = filters.SearchProfile(["Pune"], "any")


def job(**kw):
    d = {"title": "Data Analyst", "location": "Pune, Maharashtra", "employment": "Full-time", "description": JD, "status": "Needs Review"}
    d.update(kw)
    return d


def test_required_vs_preferred_skills():
    a = analyze_job(JD)
    assert set(a["required"]) == {"SQL", "Python", "Excel", "Power BI"}
    assert set(a["preferred"]) == {"Airflow", "Snowflake", "Tableau"}
    assert a["min_years"] == 0 and "Computer Science" in a["education"]
    assert "R" not in find_skills("Our team ran a report")      # no false 'R' from ordinary words


def test_explainable_score():
    r = score(job(), analyze_job(JD), PROFILE, PUNE)
    assert r["eligible"] and r["components"]["required_skills"] == 0.75   # 3 of 4 (missing Power BI)
    assert r["missing_required"] == ["Power BI"] and "Tableau" in r["matched"]
    assert set(r["missing_preferred"]) == {"Airflow", "Snowflake"}
    assert r["components"]["experience"] == 1.0 and r["components"]["location"] == 1.0 and r["components"]["title"] == 1.0
    assert r["components"]["education"] == 1.0 and 60 <= r["overall"] <= 95
    assert "Power BI" in " ".join(r["reasons"]) and r["next_action"].startswith("Find this role")


def test_mandatory_failure_caps_score():
    senior = JD.replace("0-1 years", "3+ years")
    r = score(job(description=senior), analyze_job(senior), PROFILE, PUNE)
    assert not r["eligible"] and r["overall"] <= INELIGIBLE_CAP and r["next_action"].startswith("Skip")
    r = score(job(location="Chennai, Tamil Nadu"), analyze_job(JD), PROFILE, PUNE)   # office job outside searched cities
    assert not r["eligible"] and "location" in r["mandatory_failures"][0]


def test_verified_strong_match_says_apply():
    full = {**PROFILE, "skills": PROFILE["skills"] + ["Power BI", "Airflow", "Snowflake"]}
    r = score(job(status="Verified"), analyze_job(JD), full, PUNE)
    assert r["overall"] >= 90 and r["next_action"].startswith("Strong match")


def test_no_skills_in_job_drops_that_weight():
    r = score(job(description="Data Analyst fresher role. 0-1 years."), analyze_job("Data Analyst fresher role. 0-1 years."), PROFILE, PUNE)
    assert r["components"]["required_skills"] is None and r["overall"] == 100
