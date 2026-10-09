"""Recognise ATS URLs and decide whether an ATS board demonstrably belongs to the employer.

A recognised ATS domain proves nothing on its own: anyone can open a Greenhouse board. A board is
trusted only when the employer's official website links to it (or redirects to it), or when the
vacancy is hosted on the official domain itself.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from http_client import registered_domain

KNOWN_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workday", "jobvite"}


@dataclass(frozen=True)
class AtsRef:
    ats: str
    board: str            # board token / company identifier / Workday tenant (lowercase)
    job_id: str = ""      # set when the URL points at a single vacancy
    site: str = ""        # Workday career site name
    host: str = ""        # Workday host, e.g. acme.wd5.myworkdayjobs.com
    path: str = ""        # Workday job path after the site, e.g. job/Pune/Data-Analyst_R123
    url: str = ""

    @property
    def board_key(self):
        return (self.ats, self.board.lower())


def parse_ats_url(url: str):
    """AtsRef for a recognised ATS URL, else None. Does not imply the board belongs to anyone."""
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    parts = [s for s in p.path.split("/") if s]
    qs = parse_qs(p.query)

    if host.endswith(".greenhouse.io"):
        if parts[:1] == ["embed"]:
            board = (qs.get("for") or [""])[0]
            return AtsRef("greenhouse", board.lower(), (qs.get("token") or [""])[0], url=url) if board else None
        if parts and host.split(".")[0] in ("boards", "job-boards"):
            job_id = parts[2] if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit() else ""
            return AtsRef("greenhouse", parts[0].lower(), job_id, url=url)
        return None
    if "gh_jid" in qs:  # Greenhouse job embedded on the employer's own site; board resolved from careers page
        jid = qs["gh_jid"][0]
        return AtsRef("greenhouse", "", jid, url=url) if jid.isdigit() else None
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and parts:
        return AtsRef("lever", parts[0].lower(), parts[1] if len(parts) > 1 else "", url=url)
    if host == "jobs.ashbyhq.com" and parts:
        return AtsRef("ashby", parts[0].lower(), parts[1] if len(parts) > 1 else "", url=url)
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and parts:
        m = re.match(r"(\d+)", parts[1]) if len(parts) > 1 else None
        return AtsRef("smartrecruiters", parts[0].lower(), m.group(1) if m else "", url=url)
    m = re.match(r"^([\w-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m and parts:
        if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts = parts[1:]
        if not parts:
            return None
        site = parts[0]
        is_job = len(parts) > 2 and parts[1] == "job"
        path = "/".join(parts[1:]) if is_job else ""
        rid = re.search(r"_([A-Za-z0-9-]+)$", parts[-1]) if is_job else None
        return AtsRef("workday", m.group(1).lower(), rid.group(1) if rid else "", site=site, host=host, path=path, url=url)
    if host == "jobs.jobvite.com" and parts:
        return AtsRef("jobvite", parts[0].lower(), parts[2] if len(parts) > 2 and parts[1] == "job" else "", url=url)
    return None


# Board references as they appear in careers-page HTML (links, embeds, iframes, scripts).
_BOARD_PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse\.io/(?:embed/job_board(?:/js)?\?(?:[^\"'>]*&)?for=|v1/boards/)([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?!embed\b)([\w-]+)", re.I)),
    ("lever", re.compile(r"(?:jobs(?:\.eu)?\.lever\.co|api\.lever\.co/v0/postings)/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([\w.%-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/([\w-]+)", re.I)),
]
_WORKDAY = re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)


def find_board_refs(html: str) -> set:
    refs = set()
    for ats, rx in _BOARD_PATTERNS:
        for token in rx.findall(html or ""):
            refs.add(AtsRef(ats, token.lower().rstrip(".")))
    for tenant, wd, site in _WORKDAY.findall(html or ""):
        if site.lower() not in ("wday", "static"):
            refs.add(AtsRef("workday", tenant.lower(), site=site, host=f"{tenant.lower()}.{wd.lower()}.myworkdayjobs.com"))
    return refs


def relationship(ref: AtsRef | None, url: str, official_domain: str, linked_boards) -> tuple:
    """(trusted: bool, evidence: str) for a vacancy URL relative to the employer's official domain."""
    if registered_domain(url) == official_domain and (ref is None or ref.ats == "greenhouse" and not ref.board):
        return True, f"vacancy hosted on the official domain {official_domain}"
    if ref is None:
        return False, f"{url} is neither on the official domain nor a recognised ATS"
    for b in linked_boards:
        if b.board_key == ref.board_key:
            return True, f"{ref.ats} board '{ref.board}' is linked from the official site {official_domain}"
    return False, f"{ref.ats} board '{ref.board}' is not linked from the official site {official_domain} (unverified ATS)"
