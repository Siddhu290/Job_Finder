"""ATS-style resume check against one job description. Deterministic, explainable, no AI needed.

This is an estimate of how keyword-based applicant tracking systems and recruiters screen a resume; real ATS
products differ. Components (weights, out of 100):
  JD keyword coverage 40 · job-title alignment 10 · standard sections 15 · measurable results 10 ·
  action verbs 10 · length/readability 10 · contact details 5
Suggestions never ask the user to claim skills they don't have: missing keywords are "add only if true"."""
import re

import matching

WEIGHTS = {"keywords": 40, "title": 10, "sections": 15, "impact": 10, "verbs": 10, "length": 10, "contact": 5}
SECTIONS = {
    "Education": r"\beducation\b|\bqualifications?\b|\bacademic",
    "Skills": r"\b(technical\s+)?skills\b|\btech(nical)?\s+stack\b|\btools\b",
    "Projects": r"\bprojects?\b",
    "Experience / Internships": r"\b(work\s+)?experience\b|\binternships?\b|\bemployment\b",
    "Summary / Objective": r"\bsummary\b|\bobjective\b|\bprofile\b|\babout\s+me\b",
}
ACTION_VERBS = {"achieved", "analysed", "analyzed", "automated", "built", "cleaned", "collaborated", "created", "decreased",
                "delivered", "designed", "developed", "engineered", "evaluated", "forecasted", "generated", "identified",
                "implemented", "improved", "increased", "led", "managed", "migrated", "modelled", "modeled", "optimised",
                "optimized", "organised", "organized", "presented", "processed", "reduced", "researched", "scraped",
                "streamlined", "tested", "trained", "transformed", "visualised", "visualized", "wrote", "conducted",
                "deployed", "integrated", "maintained", "monitored", "prepared", "queried", "reported", "validated"}
_BULLET = re.compile(r"^\s*(?:[-•*▪●◦]|\d+[.)])\s+(.*)$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"(\+?\d[\d\s-]{8,}\d)")
_LINK = re.compile(r"linkedin\.com/|github\.com/", re.I)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(%|x\b|k\b|\+|rows|records|users|hours|days)?", re.I)


def _lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def _bullets(text):
    lines = _lines(text)
    found = [m.group(1) for l in lines if (m := _BULLET.match(l))]
    # many PDF exports lose bullet symbols: treat short sentence-like lines starting with a verb as bullets too
    return found or [l for l in lines if len(l.split()) >= 5 and l.split()[0].lower().rstrip(",:") in ACTION_VERBS]


def score(resume: str, jd: str, job_title: str = "") -> dict:
    resume = resume or ""
    low = resume.lower()
    a = matching.analyze_job(jd or "")
    have = set(matching.find_skills(resume))
    req, pref = a["required"], a["preferred"]
    miss_req = [k for k in req if k not in have]
    miss_pref = [k for k in pref if k not in have]
    total_w = 2 * len(req) + len(pref)
    comp, tips = {}, []

    comp["keywords"] = ((2 * (len(req) - len(miss_req)) + (len(pref) - len(miss_pref))) / total_w) if total_w else None
    if miss_req:
        tips.append({"priority": "high", "text": f"The job asks for {', '.join(miss_req)}. If you have used them, name them "
                     "exactly like this in your Skills section and in a project bullet. Don't add them if you haven't."})
    if miss_pref:
        tips.append({"priority": "medium", "text": f"Nice-to-have skills you could mention if true: {', '.join(miss_pref)}."})

    title_words = [w for w in re.findall(r"[a-z]+", (job_title or "").lower()) if w not in
                   {"junior", "senior", "associate", "graduate", "trainee", "fresher", "i", "ii", "entry", "level", "the", "and", "of"}]
    if title_words:
        hit = sum(1 for w in title_words if re.search(rf"\b{re.escape(w)}", low)) / len(title_words)
        comp["title"] = hit
        if hit < 1:
            tips.append({"priority": "medium", "text": f"Use the job's title wording (“{job_title}”) in your headline or "
                         "summary, e.g. “Aspiring Data Analyst …”, so the ATS matches the role."})
    else:
        comp["title"] = None

    present = {name: bool(re.search(rx, low)) for name, rx in SECTIONS.items()}
    comp["sections"] = sum(present.values()) / len(present)
    missing_sections = [n for n, ok in present.items() if not ok]
    if missing_sections:
        tips.append({"priority": "high" if {"Skills", "Education"} & set(missing_sections) else "medium",
                     "text": "Add clearly titled sections: " + ", ".join(missing_sections) + ". ATS systems look for standard headings."})

    bullets = _bullets(resume)
    with_numbers = [b for b in bullets if _NUMBER.search(b)]
    comp["impact"] = min(1.0, len(with_numbers) / max(3, len(bullets) * 0.5)) if bullets else 0.0
    if bullets and len(with_numbers) < len(bullets) * 0.5:
        example = next((b for b in bullets if not _NUMBER.search(b)), "")
        tips.append({"priority": "medium", "text": "Quantify results where you truthfully can (rows of data, % time saved, "
                     "number of dashboards/users)." + (f" For example: “{example[:90]}”." if example else "")})

    verb_led = [b for b in bullets if b.split() and b.split()[0].lower().rstrip(",:") in ACTION_VERBS]
    comp["verbs"] = (len(verb_led) / len(bullets)) if bullets else 0.0
    if not bullets:
        tips.append({"priority": "high", "text": "Write your experience and projects as bullet points (one achievement per line)."})
    elif len(verb_led) < len(bullets) * 0.6:
        weak = next((b for b in bullets if b not in verb_led), "")
        tips.append({"priority": "low", "text": "Start bullets with an action verb (Built, Analyzed, Automated, Designed…)."
                     + (f" Rewrite e.g. “{weak[:80]}”." if weak else "")})

    words = len(re.findall(r"\w+", resume))
    comp["length"] = 1.0 if 300 <= words <= 800 else 0.7 if 200 <= words <= 1000 else 0.3
    if words < 300:
        tips.append({"priority": "medium", "text": f"Your resume is short ({words} words). Add 2–3 project bullets with tools and outcomes."})
    elif words > 1000:
        tips.append({"priority": "medium", "text": f"Your resume is long ({words} words). Freshers usually do best with one page (400–700 words)."})

    contact = [bool(_EMAIL.search(resume)), bool(_PHONE.search(resume)), bool(_LINK.search(resume))]
    comp["contact"] = sum(contact) / 3
    missing_contact = [n for n, ok in zip(("email", "phone number", "LinkedIn/GitHub link"), contact) if not ok]
    if missing_contact:
        tips.append({"priority": "low", "text": "Add your " + ", ".join(missing_contact) + " at the top."})

    used = {k: v for k, v in comp.items() if v is not None}
    overall = round(100 * sum(WEIGHTS[k] * v for k, v in used.items()) / sum(WEIGHTS[k] for k in used))
    order = {"high": 0, "medium": 1, "low": 2}
    return {"score": overall, "components": {k: (None if v is None else round(v, 2)) for k, v in comp.items()},
            "weights": WEIGHTS, "matched_keywords": [k for k in req + pref if k in have],
            "missing_required": miss_req, "missing_preferred": miss_pref, "sections": present,
            "bullets": len(bullets), "bullets_with_numbers": len(with_numbers), "words": words,
            "suggestions": sorted(tips, key=lambda t: order[t["priority"]]),
            "note": "Estimate of keyword-based screening; real ATS products differ. Only add skills you really have."}
