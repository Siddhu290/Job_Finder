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
    assert "1 suggested edit(s) were removed" in out["warnings"][0]
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
    assert r"\textbf{BI Dashboard}\par" in tex and r"\item Saved Rs. 2 lakh \textbackslash{}input\{/etc/passwd\} \$x\$" in tex
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
