"""LaTeX resumes: own .tex kept as-is, guarded per-job edits, plain text -> .tex, and version recommendations."""
import pytest

import latex_resume as lx
import resumes
from resume_parser import ResumeFileError, extract_text

TEX = r"""\documentclass[11pt]{article}
\usepackage[hidelinks]{hyperref}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\begin{document}
\begin{center}{\Huge Asha Kulkarni}\\ \href{mailto:asha@example.com}{asha@example.com}\end{center}
\section{Skills}
\textbf{Languages}{: Python, SQL, R} % keep short
\section{Projects}
\begin{itemize}
  \resumeItem{Built a sales dashboard in Power BI for 12 regions}
  \resumeItem{Cleaned 50k rows of survey data with Pandas}
\end{itemize}
\end{document}
"""


def test_detect_upload_and_plain_text():
    assert lx.is_latex(TEX) and not lx.is_latex("Asha Kulkarni\nSkills: Python")
    assert extract_text("cv.tex", TEX.encode()) == TEX                         # stored exactly as written
    with pytest.raises(ResumeFileError, match="documentclass"):
        extract_text("cv.tex", b"just some text")
    plain = lx.to_plain(TEX)
    assert "Asha Kulkarni" in plain and "asha@example.com" in plain and "Power BI for 12 regions" in plain
    assert "keep short" not in plain and "\\" not in plain and "Skills" in plain


@pytest.mark.parametrize("find, replace, ok", [
    ("Built a sales dashboard in Power BI for 12 regions", "Built a Power BI sales dashboard covering 12 regions", True),
    (r"\textbf{Languages}{: Python, SQL, R}", r"\textbf{Languages}{: SQL, Python, R}", True),         # keeps its command
    ("Built a sales dashboard in Power BI for 12 regions", "Built a sales dashboard in Power BI for 40 regions", False),   # new number
    ("Cleaned 50k rows", r"Cleaned 50k rows \input{/etc/passwd}", False),                            # file access
    ("Cleaned 50k rows", r"\textbf{Cleaned} 50k rows", False),                                       # adds a command
    ("Cleaned 50k rows", "Cleaned 50k rows {", False),                                               # unbalanced
    ("Python", "Python 3", False),                                                                     # not unique + number
    ("Kotlin developer", "Senior Kotlin developer", False),                                            # not in the resume
    (r"\newcommand{\resumeItem}[1]{\item\small{#1}}", r"\newcommand{\resumeItem}[1]{\item{#1}}", False),   # definitions never
])
def test_edit_guards(find, replace, ok):
    assert (lx.check_edit(TEX, find, replace) == "") is ok


def test_guard_edits_flags_new_skills_and_reports_rejections():
    out = lx.guard_edits(TEX, {"summary": "Angled to BI.", "keywords": ["Power BI", "Tableau"], "edits": [
        {"find": "Cleaned 50k rows of survey data with Pandas", "replace": "Cleaned 50k rows of survey data with Pandas and Tableau", "reason": "JD"},
        {"find": "Built a sales dashboard", "replace": "Built a sales dashboard \\write18{rm}", "reason": "x"}]})
    assert out["mode"] == "latex" and len(out["edits"]) == 1 and "Tableau" in out["edits"][0]["warning"]
    assert "1 suggestion(s) were removed" in out["warnings"][0]
    assert {k["keyword"]: k["in_resume"] for k in out["keywords"]} == {"Power BI": True, "Tableau": False}


def test_apply_edits_rechecks_and_keeps_layout():
    edits = [{"find": "Built a sales dashboard in Power BI for 12 regions", "replace": "Built a Power BI sales dashboard for 12 regions"},
             {"find": "Built a sales dashboard in Power BI for 12 regions", "replace": "again"},          # gone after the first
             {"find": "Cleaned 50k rows", "replace": r"Cleaned 50k rows\include{x}"}]                       # forged by a client
    r = lx.apply_edits(TEX, edits)
    assert r["applied"] == 1 and len(r["skipped"]) == 2
    assert r["tex"] == TEX.replace("Built a sales dashboard in Power BI for 12 regions", "Built a Power BI sales dashboard for 12 regions")


def test_plain_text_to_latex_escapes_everything():
    tex = lx.to_latex("Asha K\nasha@example.com | github.com/asha_k\nSKILLS\nLanguages: C# & SQL, 100%\nPROJECTS\nBI Dashboard\n"
                      "- Saved Rs. 2 lakh \\input{/etc/passwd} $x$ ~ ^\n")
    assert r"\href{mailto:asha@example.com}{asha@example.com}" in tex and r"\href{https://github.com/asha_k}{github.com/asha\_k}" in tex
    assert r"\textbf{Languages:} C\# \& SQL, 100\%" in tex and r"\rsec{Skills}" in tex and r"\usepackage{titlesec}" not in tex and r"\usepackage{enumitem}" not in tex
    assert r"\etitle{BI Dashboard}" in tex and r"\item Saved Rs. 2 lakh \textbackslash{}input\{/etc/passwd\} \$x\$" in tex
    assert tex.count(r"\input{") == 1      # only the template's own \input{glyphtounicode}


class St:
    def __init__(self):
        self.docs = {}

    def get_json(self, k):
        return self.docs.get(k)

    def put_json(self, k, v):
        self.docs[k] = v


@pytest.fixture
def st(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")
    return St()


JD = "We need a Data Analyst. Required: SQL, Python, Power BI, Excel. Nice to have: Tableau. Freshers welcome. " * 3


def test_format_is_recorded_and_ats_uses_plain_text(st):
    v = resumes.save(st, "My LaTeX", TEX, "upload")
    assert v["format"] == "latex" and resumes.get_text(st, v["id"]) == TEX.strip()
    assert "\\" not in resumes.plain_text(st, v["id"])


def test_recommends_the_closest_tailored_version(st):
    base = resumes.save(st, "Base", TEX, "upload")
    resumes.save(st, "Acme – Data Analyst", TEX.replace("Pandas", "Pandas and SQL"), "tailored", "Data Analyst · Acme",
                 "Junior Data Analyst", ["sql", "python", "power bi", "excel"])
    resumes.save(st, "Beta – Python Dev", TEX, "tailored", "Python Developer · Beta", "Python Developer", ["python", "django"])
    r = resumes.recommend(st, "Data Analyst (Fresher)", JD, base["id"])
    assert r["version"]["name"] == "Acme – Data Analyst" and r["role_match"] == 100       # 'Junior'/'Fresher' ignored
    assert r["skill_overlap"] >= 60 and isinstance(r["ats"], int) and isinstance(r["current_ats"], int)
    assert resumes.recommend(st, "Mechanical Design Engineer", "AutoCAD SolidWorks " * 20) is None   # nothing similar


JD_BI = "Data Analyst. Required: SQL, Power BI, Tableau, Excel. You will build dashboards and reports. " * 3


@pytest.mark.parametrize("find, replace, ok", [
    ("Built a sales dashboard in Power BI for 12 regions", "Built a sales dashboard in Power BI and SQL for 12 regions", True),   # adds a JD keyword the resume has
    (r"\textbf{Languages}{: Python, SQL, R}", r"\textbf{Languages}{: SQL, Python, R}", True),                                     # reorder
    ("Built a sales dashboard in Power BI for 12 regions", "Spearheaded an enterprise analytics initiative for 12 regions", False),  # rewrite
    ("Cleaned 50k rows of survey data with Pandas", "Cleaned 50k rows", False),                                                    # removes too much
    ("Cleaned 50k rows of survey data with Pandas", "Cleaned 50k rows of survey data with Pandas and Tableau", True),              # JD keyword: allowed, flagged later
])
def test_keyword_only_edits(find, replace, ok):
    assert (lx.check_edit(TEX, find, replace, lx.keyword_vocab(TEX, JD_BI)) == "") is ok


def test_apply_rechecks_keyword_only_with_the_job():
    r = lx.apply_edits(TEX, [{"find": "Built a sales dashboard in Power BI for 12 regions",
                              "replace": "Spearheaded an enterprise analytics initiative for 12 regions"}], JD_BI)
    assert r["applied"] == 0 and "only keywords" in r["skipped"][0]["reason"]


def test_default_layout_matches_the_sample_resume():
    tex = lx.to_latex("""Siddharth More
Aspiring Python Developer
sid@example.com | 9518508756 | github.com/Siddhu290
EDUCATION
MET Institute of Engineering | Nashik, Maharashtra
Bachelor of Engineering | Aug 2021 – Jul 2025
EXPERIENCE
Odoo Python Developer | Alligator Infosoft (On-Site)
Sept 2025 – Present
- Developed custom ERP modules using Python
RELEVANT PROJECTS
Mood Mate – Python, OpenCV
- Built an emotion-aware chatbot
CERTIFICATIONS AND TRAINING
- SQL
""")
    assert r"{\Large\bfseries SIDDHARTH MORE}" in tex and r"{\small\itshape Aspiring Python Developer}" in tex
    assert r"sid@example.com} \textbullet{} 9518508756" in tex
    for h in ("Education", "Experience", "Relevant Projects", "Certifications And Training"):
        assert r"\rsec{" + h + "}" in tex
    assert r"\entry{MET Institute of Engineering}{Nashik, Maharashtra}" in tex
    assert r"\subentry{Bachelor of Engineering}{Aug 2021 – Jul 2025}" in tex
    assert r"\entry{Odoo Python Developer}{Alligator Infosoft (On-Site)}" in tex and r"\etitle{Mood Mate – Python, OpenCV}" in tex
    assert not any(p in tex for p in (r"\usepackage{titlesec}", r"\usepackage{enumitem}", r"\usepackage{marvosym}"))


def test_one_page_fit_level_follows_length_and_is_set_in_the_tex():
    short = "Asha\nasha@example.com\nSKILLS\nPython, SQL\n"
    long_ = short + "EXPERIENCE\n" + "\n".join(f"- Built reporting pipeline number {i} for the finance team using SQL" for i in range(80))
    assert lx.fit_level(short.splitlines()) == 0 and lx.fit_level(long_.splitlines()) == 4
    tex = lx.to_latex(short)
    assert r"\def\fitlevel{0}" in tex and "FITLEVEL" not in tex
    assert r"\pdfinterwordspaceon" in tex and r"\hyphenpenalty=10000" in tex      # ATS: real spaces, no split words


JAKE = r"""\documentclass{article}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\begin{document}
\section{Projects}
\textbf{Mood Mate} $|$ \emph{Python, OpenCV, Django, MongoDB}
\begin{itemize}
    \resumeItem{Built an emotion-aware chatbot using OpenCV}
\end{itemize}
\section{Skills}
Frameworks: Django, REST APIs
\end{document}
"""
JD_DJ = "Python Developer. Required: Django, REST APIs, MongoDB, Python. Build backend services. " * 3


@pytest.mark.parametrize("text, evidence, ok", [
    ("Developed the Django backend with MongoDB for the chatbot", "Python, OpenCV, Django, MongoDB", True),
    ("Integrated REST APIs in the Django backend", "Frameworks: Django, REST APIs", True),
    ("Led a team of 5 engineers on the chatbot", "Python, OpenCV, Django, MongoDB", False),          # new number + unbacked words
    ("Deployed the chatbot on AWS Kubernetes", "Python, OpenCV, Django, MongoDB", False),           # skills not in resume
    ("Developed the Django backend", "Django experts wanted", False),                                # evidence not in resume
    (r"Built \input{x} backend", "Python, OpenCV, Django, MongoDB", False),                           # no LaTeX in a bullet
])
def test_new_bullets_must_be_backed_by_the_resume(text, evidence, ok):
    after = "Built an emotion-aware chatbot using OpenCV"
    why = lx.check_addition(JAKE, after, text, evidence, lx.to_plain(JAKE), lx.keyword_vocab(JAKE, JD_DJ))
    assert (why == "") is ok, why


def test_new_bullet_copies_the_templates_own_formatting_and_cannot_float():
    r = lx.apply_edits(JAKE, [{"type": "add", "after": "Built an emotion-aware chatbot using OpenCV",
                               "text": "Developed the Django backend with MongoDB for the chatbot", "evidence": "Python, OpenCV, Django, MongoDB"},
                              {"type": "add", "after": "Frameworks: Django, REST APIs",           # not a bullet line
                               "text": "Integrated REST APIs in the Django backend", "evidence": "Frameworks: Django, REST APIs"}], JD_DJ)
    assert r["applied"] == 1 and "must follow an existing bullet" in r["skipped"][0]["reason"]
    assert "    \\resumeItem{Built an emotion-aware chatbot using OpenCV}\n    \\resumeItem{Developed the Django backend with MongoDB for the chatbot}\n" in r["tex"]


def test_pdf_text_round_trip_keeps_hyphens_titles_and_wrapped_bullets():
    text = ("Asha Kulkarni\nasha@example.com\nEXPERIENCE\nOdoo Python Developer (Sept 2025 – Present)\n"
            "• Built a data‑science‑focused dashboard for weekly reporting using Python, SQL and\nPower BI with the sales team.\n"
            "MET Institute of Engineering Nashik, Maharashtra\nEDUCATION\nB.E. Computer Engineering Aug 2021 – Jul 2025\n")
    tex = lx.to_latex(text)
    assert "data-science-focused" in tex                                              # non-breaking hyphens kept
    assert r"\entry{Odoo Python Developer}{Sept 2025 – Present}" in tex                # bracketed dates go right
    assert (r"\item Built a data-science-focused dashboard for weekly reporting using \textbf{Python}, \textbf{SQL} and "
            r"\textbf{Power BI} with the sales team.") in tex                       # one bullet again, skills in bold
    assert r"{MET Institute of Engineering}{Nashik, Maharashtra}" in tex


PDF_TEXT = """Siddharth More
siddharth29m@gmail.com | 9518508756
EDUCATION
MET Institute of Engineering Nashik, Maharashtra
Bachelor of Engineering Aug 2021 – Jul 2025
EXPERIENCE
Odoo Python Developer Alligator Infosoft (On-Site)
Sept 2025 – Present
• Developed custom ERP modules using Python, XML, and PostgreSQL.
TECHNICAL SKILLS
Languages: Python, SQL
"""


def test_details_are_read_checked_and_corrections_drive_the_resume():
    d = lx.parse_details(PDF_TEXT)
    assert d["name"] == "Siddharth More" and d["contacts"] == ["siddharth29m@gmail.com", "9518508756"]
    job = d["sections"][1]["blocks"][0]
    assert job["title"] == "Odoo Python Developer Alligator Infosoft (On-Site)" and job["sub"] == "Sept 2025 – Present"
    asks = [i["message"] for i in lx.check_details(d)]
    assert any("joined to the title" in m for m in asks) and not any("No email" in m for m in asks)
    # the user splits the company out of the title, moves the dates right, and the resume follows exactly
    job.update(title="Odoo Python Developer", right="Alligator Infosoft (On-Site)", sub="", sub_right="Sept 2025 – Present")
    fixed = lx.clean_details(d)
    assert not any("joined to the title" in i["message"] for i in lx.check_details(fixed))
    tex = lx.render_details(fixed)
    assert r"\entry{Odoo Python Developer}{Alligator Infosoft (On-Site)}" in tex and r"\subentry{}{Sept 2025 – Present}" in tex
    assert "Odoo Python Developer | Alligator Infosoft (On-Site)" in lx.details_to_text(fixed)


def test_checks_ask_for_missing_essentials():
    d = lx.parse_details("Asha\nPune\nPROJECTS\nDashboard\n- Built it\n")
    asks = " ".join(i["message"] for i in lx.check_details(d))
    assert "No email" in asks and "No phone" in asks and "No Education" in asks and "No Skills" in asks


def test_clean_details_rejects_junk_and_escapes_on_render():
    with pytest.raises(ValueError):
        lx.clean_details("not a dict")
    d = lx.clean_details({"name": "A" * 500, "contacts": ["a@b.co"] * 50, "sections": [{"title": "Skills", "blocks": [
        {"type": "line", "label": "Hack", "text": r"\input{/etc/passwd} & 100%"}, {"type": "evil", "text": "x"}]}]})
    assert len(d["name"]) == 80 and len(d["contacts"]) == lx.LIMITS["contacts"] and len(d["sections"][0]["blocks"]) == 1
    tex = lx.render_details(d)
    assert r"\textbackslash{}input\{/etc/passwd\} \& 100\%" in tex and tex.count(r"\input{") == 1


def test_checked_details_are_stored_encrypted_and_used_for_tailoring(st):
    v = resumes.save(st, "From PDF", PDF_TEXT + "Extra line so it is long enough for a resume version to be stored.\n", "upload")
    assert resumes.get_details(st, v["id"]) is None
    d = lx.parse_details(PDF_TEXT)
    d["sections"][1]["blocks"][0].update(title="Odoo Python Developer", right="Alligator Infosoft (On-Site)")
    v2 = resumes.set_details(st, v["id"], lx.clean_details(d))
    assert v2["checked"] and "Odoo Python Developer" not in str(st.docs[f"_resume_{v['id']}"])     # encrypted at rest
    assert r"\entry{Odoo Python Developer}{Alligator Infosoft (On-Site)}" in resumes.tex_for(st, v["id"])
    assert "Odoo Python Developer | Alligator Infosoft (On-Site)" in resumes.plain_text(st, v["id"])  # ATS uses the corrected text


SAMPLE_PROFILE = {
    "name": "Siddharth More", "tagline": "Aspiring Python Developer", "email": "sid@example.com", "phone": "9518508756",
    "linkedin": "linkedin.com/in/sid", "github": "", "location": "", "summary": "",
    "education": [{"school": "MET Institute of Engineering", "place": "Nashik, Maharashtra", "degree": "B.E. AI & Data Science",
                   "dates": "Aug 2021 – Jul 2025", "score": "7.60 / 10.00", "details": []}],
    "experience": [{"role": "Odoo Python Developer", "company": "Alligator Infosoft", "place": "On-Site", "dates": "Sept 2025 – Present",
                    "bullets": ["Developed custom ERP modules using Python, XML, and PostgreSQL."]}],
    "projects": [{"name": "Mood Mate", "tech": "Python, OpenCV, Django", "dates": "", "bullets": ["Deployed on Django with MongoDB."]}],
    "skills": [{"label": "Frameworks", "values": "Django, Frappe, ERPNext"}],
    "certifications": ["Machine Learning Training – Symbiosis (2024)"], "achievements": [], "extra": []}


def test_profile_renders_the_standard_format():
    p = lx.clean_profile(SAMPLE_PROFILE)
    tex = lx.render_details(lx.profile_to_details(p))
    assert r"\entry{MET Institute of Engineering}{Nashik, Maharashtra}" in tex
    assert r"\subentry{B.E. AI \& Data Science}{Aug 2021 – Jul 2025}" in tex
    assert r"\entry{Odoo Python Developer}{Alligator Infosoft (On-Site)}" in tex and r"\subentry{}{Sept 2025 – Present}" in tex
    assert r"\etitle{Mood Mate – Python, OpenCV, Django}" in tex and r"\item Deployed on \textbf{Django} with \textbf{MongoDB}." in tex
    assert r"\item \textbf{Machine Learning Training} – Symbiosis (2024)" in tex
    assert r"\sectiondivider" in tex and "colorlinks=true" in tex and r"\IfFileExists{ptmr8t.tfm}" in tex
    assert lx.check_profile(p) == []


def test_import_maps_an_uploaded_resume_onto_the_profile_fields():
    p = lx.details_to_profile(lx.parse_details(PDF_TEXT))
    assert (p["name"], p["email"], p["phone"]) == ("Siddharth More", "siddharth29m@gmail.com", "9518508756")
    assert p["education"][0]["school"] == "MET Institute of Engineering" and p["education"][0]["dates"] == "Aug 2021 – Jul 2025"
    assert p["skills"] == [{"label": "Languages", "values": "Python, SQL"}]
    asks = [i["message"] for i in lx.check_profile(p)]
    assert any("add the company" in m for m in asks)                  # the role had the company glued on in the PDF text


def test_my_profile_is_encrypted_and_keeps_one_resume_in_sync(st):
    out = resumes.save_profile(st, {"name": "Asha"})
    assert out["version"] is None and "Add a bit more" in out["note"] and resumes.get_profile(st)["name"] == "Asha"
    first = resumes.save_profile(st, SAMPLE_PROFILE)["version"]
    assert first["name"] == resumes.PROFILE_RESUME_NAME and first["source"] == "profile"
    assert "Alligator" not in str(st.docs[resumes.PROFILE_DOC])                                  # encrypted at rest
    second = resumes.save_profile(st, {**SAMPLE_PROFILE, "tagline": "Odoo Developer"})["version"]
    assert second["id"] == first["id"] and len(resumes.list_versions(st)) == 1                  # updated, not duplicated
    assert "Odoo Developer" in resumes.tex_for(st, first["id"])
