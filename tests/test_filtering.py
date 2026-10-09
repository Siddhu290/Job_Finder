from datetime import date

import pytest

from filters import (BORDERLINE, ELIGIBLE, TOO_SENIOR, UNKNOWN, experience_check, is_fresh, location_check,
                     parse_posted, title_check)


@pytest.mark.parametrize("title", [
    "Data Analyst", "Junior Data Analyst", "Associate Data Engineer", "Graduate Data Engineer (Remote)",
    "Data Analyst Trainee", "Entry-Level Data Analyst", "Analytics Engineer", "BI Analyst", "Data Engineer I",
    "Analytics Trainee", "Analytical Engineer (Data Modeller + Data Analyst) (India)",
])
def test_relevant_titles(title):
    assert title_check(title)[0], title


@pytest.mark.parametrize("title", [
    "Senior Data Analyst", "Lead Data Engineer", "Data Engineer II", "Data Engineering Manager", "Sr. Data Analyst",
    "Software Engineer", "Data Entry Operator", "Data Analyst Intern", "Principal Data Engineer", "Data Engineer 3",
    "Business Development Executive",
])
def test_irrelevant_titles(title):
    assert not title_check(title)[0], title


@pytest.mark.parametrize("text,verdict", [
    ("Experience: 0-1 years in SQL", ELIGIBLE),
    ("Freshers are welcome to apply", ELIGIBLE),
    ("0 to 1 yrs of experience", ELIGIBLE),
    ("6 months of experience with Python preferred", ELIGIBLE),
    ("Experience: 0–2 years", ELIGIBLE),           # en dash, open to 0 years
    ("2026 batch graduates may apply", ELIGIBLE),
    ("Minimum 3 years of experience in data engineering", TOO_SENIOR),
    ("2+ years experience with Spark", TOO_SENIOR),
    ("Experience: 2-4 years", TOO_SENIOR),
    ("Freshers need not apply. Experience with SQL required.", TOO_SENIOR),
    ("1+ years of experience in analytics", BORDERLINE),
    ("Great team, competitive pay, Python and SQL skills.", UNKNOWN),
    ("Bachelor's degree, 4 years program", UNKNOWN),          # number not about experience
])
def test_experience(text, verdict):
    assert experience_check(text)[0] == verdict, experience_check(text)


def test_junior_title_alone_is_not_evidence_of_eligibility():
    assert experience_check("Junior Data Analyst")[0] == UNKNOWN


@pytest.mark.parametrize("loc,desc,remote,ok", [
    ("Pune, Maharashtra, India", "Work from office 5 days a week", False, True),     # Pune: office is fine
    ("Hinjewadi, Pune", "", False, True),
    ("Pune (Hybrid)", "", False, True),
    ("Bengaluru, Karnataka, India", "Work from office", False, True),              # Bengaluru: office is fine
    ("Whitefield, Bangalore", "", False, True),
    ("Nashik, Maharashtra", "", False, True),
    ("Hyderabad, Telangana", "", False, False),                                     # other city, office
    ("Guwahati, Assam", "", False, False),
    ("Mumbai (Hybrid)", "Hybrid, 3 days in office", False, False),
    ("Chennai, Tamil Nadu", "", True, True),                                        # other city, WFH flag
    ("Thiruvananthapuram, Keralam", "This is a fully remote role.", False, True),
    ("Remote", "This is a fully remote role open to candidates based in India.", True, True),
    ("Anywhere", "Remote; we hire across India and APAC.", True, True),
    ("Remote", "Work from anywhere!", True, False),                                # worldwide, India not explicit
    ("Remote", "Remote in India, but you must be located in the United States.", True, False),
    ("London, UK", "", False, False),
    ("San Francisco, CA", "We also have an office in India", False, False),
])
def test_location(loc, desc, remote, ok):
    assert location_check(loc, desc, remote)[0] is ok


def test_freshness():
    today = date(2026, 10, 9)
    assert parse_posted("3 days ago", today) == date(2026, 10, 6)
    assert parse_posted("Posted 30+ Days Ago", today) == date(2026, 9, 9)
    assert parse_posted("5 hours ago", today) == today
    assert parse_posted("2026-10-01T10:00:00Z", today) == date(2026, 10, 1)
    assert parse_posted(1791504000000, today) is not None
    assert is_fresh(date(2026, 10, 3), 7, today)
    assert not is_fresh(date(2026, 9, 30), 7, today)
    assert is_fresh(None, 7, today)  # unknown date: kept, decided by verification


@pytest.fixture
def profile():
    import filters
    yield filters.set_profile
    filters.set_profile()  # back to the default for other tests


@pytest.mark.parametrize("locs,mode,loc,desc,remote,ok", [
    (["Mumbai"], "any", "Andheri, Mumbai", "Work from office", False, True),        # alias locality
    (["Mumbai"], "any", "Pune, Maharashtra", "", False, False),                      # not a searched city
    (["Mumbai"], "any", "Chennai", "fully remote role, India", True, True),          # WFH anywhere in India
    (["Mumbai"], "onsite", "Chennai", "fully remote role, India", True, False),      # office/hybrid only
    (["Mumbai"], "wfh", "Mumbai (Hybrid)", "", False, False),                         # WFH only
    (["Mumbai"], "wfh", "Mumbai", "", True, True),
    (["Bangalore"], "any", "Whitefield, Bengaluru", "", False, True),               # alias input
    (["Indore"], "onsite", "Indore, Madhya Pradesh", "", False, True),              # unknown city, plain name
])
def test_search_profiles(profile, locs, mode, loc, desc, remote, ok):
    from filters import location_check
    profile(locs, mode)
    assert location_check(loc, desc, remote)[0] is ok, location_check(loc, desc, remote)


def test_resume_roles_and_experience(profile):
    import filters
    profile(["Pune"], "any", roles=["Business Analyst", "Python Developer"], skills=["Python", "SQL", "Power BI"], max_years=2)
    assert title_check("Junior Business Analyst - Pune")[0]
    assert title_check("Python Developer (Fresher)")[0]
    assert not title_check("Data Analyst")[0]                   # not one of the resume roles any more
    assert not title_check("Senior Python Developer")[0]        # still excludes senior levels
    assert experience_check("1-2 years of experience")[0] == ELIGIBLE   # within the resume's 2 years
    assert experience_check("3+ years of experience")[0] == TOO_SENIOR
    hits, total = filters.skill_match("We use Python, SQL and Excel daily")
    assert hits == ["python", "sql"] and total == 3
