"""Internal job model shared by discovery, verification and storage."""
from dataclasses import dataclass, field
from datetime import date

VERIFIED = "Verified"
NEEDS_REVIEW = "Needs Review"
REJECTED = "Rejected"
CLOSED = "Closed"
STATUSES = {VERIFIED, NEEDS_REVIEW, REJECTED, CLOSED}
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
# Order shown in the verification breakdown
CHECKS = ["employer", "official_site", "careers_page", "ats_link", "vacancy_match", "requisition_id",
          "open_status", "apply_url", "experience", "location"]
BUDGET_NOTE = "not verified: SerpApi budget for this run used up"
PENDING_NOTE = "not verified yet: the search ran out of time; it is verified automatically in your next search"


@dataclass
class Job:
    title: str
    company: str
    location: str = ""
    employment_type: str = ""
    description: str = ""
    listing_url: str = ""          # where we discovered it (may be a job board)
    posted_date: date | None = None
    req_id: str = ""
    source: str = ""               # e.g. "Google Jobs via LinkedIn", "Greenhouse"
    remote: bool = False
    links: list = field(default_factory=list)   # unverified links seen during discovery

    # filled by filtering / verification
    experience: str = ""           # human-readable requirement, e.g. "0-1 years"
    status: str = ""
    careers_url: str = ""
    apply_url: str = ""            # only ever set when status == VERIFIED
    notes: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    # transparent verification breakdown: name -> {"status": pass|fail|unknown, "detail": str, "url": str}
    checks: dict = field(default_factory=dict)
    retry: bool = False            # Needs Review for a transient reason (budget, network): re-check later
    closes: str = ""               # application deadline published by the employer (ISO date), if any
    # recruiter/HR contacts with provenance: type is "published" (in the employer's own posting),
    # "listing" (in a portal's copy, unverified) or "profile" (public profile from search results, unverified)
    contacts: list = field(default_factory=list)
    attempts: int = 0              # verification attempts so far (retry queue)
    pending: bool = False          # saved without verification because the run ran out of time

    def check(self, name, status, detail, url=""):
        self.checks[name] = {"status": status, "detail": detail[:300], "url": url}

    def note(self, msg):
        self.notes.append(msg)

    def ev(self, msg):
        self.evidence.append(msg)


@dataclass
class Posting:
    """A vacancy as reported by the employer's own system (ATS API or official page)."""
    ats: str
    url: str                       # direct application/vacancy URL from the employer system
    title: str
    location: str = ""
    description: str = ""
    req_id: str = ""
    posted_date: date | None = None
    employment_type: str = ""
    company: str = ""
    active: bool | None = None     # True only when the employer system lists it as open
    remote: bool = False
    valid_through: str = ""        # ISO date from the employer's JobPosting data, if published
    evidence: list = field(default_factory=list)
