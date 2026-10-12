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


def save(st, name: str, text: str, source: str = "pasted", job: str = "", role: str = "", job_skills=None) -> dict:
    """role / job_skills: the job a tailored version was made for, so it can be recommended for similar jobs."""
    import latex_resume
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
         "chars": min(len(text), MAX_CHARS), "format": "latex" if latex_resume.is_latex(text) else "text",
         "role": str(role or "")[:120], "job_skills": [str(s)[:40] for s in (job_skills or [])][:40]}
    st.put_json(f"_resume_{v['id']}", {"text": user_secrets.encrypt_text(text[:MAX_CHARS])})
    st.put_json(INDEX, {"versions": versions + [v]})
    return v


def get_text(st, vid: str) -> str:
    if not any(v["id"] == vid for v in _index(st)):
        raise KeyError(vid)
    return user_secrets.decrypt_text((st.get_json(f"_resume_{vid}") or {}).get("text", ""))


def get_details(st, vid: str):
    """The user-checked details of a version (dict), or None if they haven't been checked yet."""
    import json
    if not any(v["id"] == vid for v in _index(st)):
        raise KeyError(vid)
    enc = (st.get_json(f"_resume_{vid}") or {}).get("details")
    return json.loads(user_secrets.decrypt_text(enc)) if enc else None


def set_details(st, vid: str, details: dict) -> dict:
    """Store checked details (encrypted); the version's text becomes the details' text, so ATS scores, matching and
    tailoring all use the corrected resume."""
    import json
    import latex_resume
    versions = _index(st)
    v = next((x for x in versions if x["id"] == vid), None)
    if not v:
        raise KeyError(vid)
    text = latex_resume.details_to_text(details)[:MAX_CHARS]
    if len(text) < 100:
        raise ResumeError("The resume text is too short")
    st.put_json(f"_resume_{vid}", {"text": user_secrets.encrypt_text(text), "details": user_secrets.encrypt_text(json.dumps(details))})
    v.update(chars=len(text), format="text", checked=datetime.now().strftime("%Y-%m-%d %H:%M"))
    st.put_json(INDEX, {"versions": versions})
    return v


def tex_for(st, vid: str) -> str:
    """The .tex a version is tailored and printed from: the user's own LaTeX, else the default template filled from
    the checked details, else from the version's text."""
    import latex_resume
    t = get_text(st, vid)
    if latex_resume.is_latex(t):
        return t
    d = get_details(st, vid)
    return latex_resume.render_details(d) if d else latex_resume.to_latex(t)


def plain_text(st, vid: str) -> str:
    """Readable text of a version (a LaTeX version is converted), for ATS scoring, matching and the AI profile."""
    import latex_resume
    t = get_text(st, vid)
    return latex_resume.to_plain(t) if latex_resume.is_latex(t) else t


_LEVEL_WORDS = {"junior", "jr", "senior", "sr", "fresher", "freshers", "trainee", "intern", "internship", "associate", "entry",
                "level", "graduate", "grad", "i", "ii", "iii", "1", "2", "3", "lead", "the", "a", "an", "for", "and", "of", "in",
                "at", "remote", "hybrid", "wfh", "work", "from", "home", "fulltime", "full", "time", "contract", "role"}


def role_words(title: str) -> set:
    from verification.vacancy_matcher import norm_title
    return set(norm_title(title).split()) - _LEVEL_WORDS


def recommend(st, job_title: str, description: str, current_id: str = "", min_score: float = 0.5):
    """The saved tailored version made for the most similar job (role words + the skills the job asks for), scored
    with the ATS check against this job, next to the currently selected version. Local only: no AI call. None if
    no tailored version is similar enough."""
    import ats
    import matching
    want_role, want_skills = role_words(job_title), {k.lower() for k in matching.find_skills(description or "")}
    best = None
    for v in _index(st):
        if v.get("source") != "tailored" or not (v.get("role") or v.get("job_skills")):
            continue
        rw, sk = role_words(v.get("role", "")), {k.lower() for k in v.get("job_skills") or []}
        role_sim = len(rw & want_role) / len(rw | want_role) if rw | want_role else 0
        skill_sim = len(sk & want_skills) / len(sk | want_skills) if sk | want_skills else 0
        sim = 0.6 * role_sim + 0.4 * skill_sim
        if sim >= min_score and (best is None or sim > best[0]):
            best = (sim, v, role_sim, skill_sim)
    if not best:
        return None
    sim, v, role_sim, skill_sim = best
    out = {"version": v, "similarity": round(sim * 100), "role_match": round(role_sim * 100), "skill_overlap": round(skill_sim * 100),
           "ats": ats.score(plain_text(st, v["id"]), description, job_title)["score"] if description else None}
    if current_id and current_id != v["id"]:
        try:
            out["current_ats"] = ats.score(plain_text(st, current_id), description, job_title)["score"] if description else None
        except KeyError:
            pass
    return out


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
