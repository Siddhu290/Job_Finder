"""Read vacancies from ATS public job-board APIs and from schema.org JobPosting markup on official pages.

These public endpoints only list currently published vacancies, so a posting returned here is
treated as "listed as open by the employer's system". A 404/absence means the vacancy is gone.
"""
import html
import json
import re
from datetime import date
from functools import lru_cache

import http_client
from filters import parse_posted
from models import Posting
from verification.ats_verifier import AtsRef

CLOSED_MARKERS = re.compile(
    r"no longer (accepting applications|available|open|active)|position (has been|is) (filled|closed)"
    r"|job (posting )?(has )?expired|(this|the) (job|position|vacancy|posting) (is|has been) (closed|removed|filled)"
    r"|applications? (are |is )?(now )?closed|job not found|posting (is )?closed", re.I)


def _text(s):
    return http_client.html_to_text(html.unescape(s or ""))


# ---------------- single posting ----------------
@lru_cache(maxsize=512)
def fetch_posting(ref: AtsRef):
    """Posting for ref.job_id, None if the employer system no longer lists it. Raises on transport errors.
    Jobvite has no public API -> ValueError (caller treats as unverifiable)."""
    if not ref.board or not ref.job_id:
        raise ValueError(f"incomplete ATS reference {ref}")
    fn = {"greenhouse": _gh_one, "lever": _lever_one, "ashby": _ashby_one,
          "smartrecruiters": _sr_one, "workday": _wd_one}.get(ref.ats)
    if not fn:
        raise ValueError(f"no public API to verify {ref.ats} postings")
    return fn(ref)


def _gh(d, board):
    return Posting(
        ats="greenhouse", url=d.get("absolute_url", ""), title=d.get("title", "").strip(),
        location=(d.get("location") or {}).get("name", ""), description=_text(d.get("content")),
        req_id=str(d.get("id", "")), posted_date=parse_posted(d.get("first_published") or d.get("updated_at")),
        company=d.get("company_name", ""), active=True,
        evidence=[f"listed on Greenhouse public board API (board '{board}', job {d.get('id')})"])


def _gh_one(ref):
    d = http_client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{ref.board}/jobs/{ref.job_id}")
    return _gh(d, ref.board) if d else None


def _lever(d, board):
    cats = d.get("categories") or {}
    lists = " ".join(f"{x.get('text', '')}: {_text(x.get('content'))}" for x in d.get("lists") or [])
    return Posting(
        ats="lever", url=d.get("hostedUrl", ""), title=d.get("text", "").strip(), location=cats.get("location", ""),
        description=" ".join([d.get("descriptionPlain", ""), lists, d.get("additionalPlain", "")]),
        req_id=d.get("id", ""), posted_date=parse_posted(d.get("createdAt")), employment_type=cats.get("commitment", ""),
        remote=d.get("workplaceType") == "remote", active=True,
        evidence=[f"listed on Lever public postings API (board '{board}', posting {d.get('id')})"])


def _lever_one(ref):
    d = http_client.get_json(f"https://api.lever.co/v0/postings/{ref.board}/{ref.job_id}")
    return _lever(d, ref.board) if d else None


def _ashby(d, board):
    loc = ", ".join(filter(None, [d.get("location", "")] + [x.get("location", "") for x in d.get("secondaryLocations") or []]))
    return Posting(
        ats="ashby", url=d.get("jobUrl", ""), title=d.get("title", "").strip(), location=loc,
        description=d.get("descriptionPlain", ""), req_id=d.get("id", ""), posted_date=parse_posted(d.get("publishedAt")),
        employment_type=d.get("employmentType", ""), remote=bool(d.get("isRemote")), active=d.get("isListed", True) is not False,
        evidence=[f"listed on Ashby public job-board API (board '{board}', job {d.get('id')})"])


def _ashby_board(board):
    d = http_client.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=false")
    return (d or {}).get("jobs") or []


def _ashby_one(ref):
    hit = next((j for j in _ashby_board(ref.board) if j.get("id") == ref.job_id), None)
    return _ashby(hit, ref.board) if hit else None


def _sr(d, board):
    loc = d.get("location") or {}
    secs = ((d.get("jobAd") or {}).get("sections") or {})
    desc = " ".join(_text((secs.get(k) or {}).get("text")) for k in ("jobDescription", "qualifications", "additionalInformation"))
    return Posting(
        ats="smartrecruiters", url=d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{board}/{d.get('id')}",
        title=d.get("name", "").strip(), location=", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])),
        description=desc, req_id=str(d.get("id", "")), posted_date=parse_posted(d.get("releasedDate")),
        employment_type=(d.get("typeOfEmployment") or {}).get("label", ""), company=(d.get("company") or {}).get("name", ""),
        remote=bool(loc.get("remote")), active=d.get("active", True) is not False,
        evidence=[f"listed on SmartRecruiters public postings API (company '{board}', posting {d.get('id')})"])


def _sr_one(ref):
    d = http_client.get_json(f"https://api.smartrecruiters.com/v1/companies/{ref.board}/postings/{ref.job_id}")
    return _sr(d, ref.board) if d else None


def _wd_one(ref):
    # Workday's career-site JSON endpoint is not a documented public API, so robots.txt is honoured.
    d = http_client.get_json(f"https://{ref.host}/wday/cxs/{ref.board}/{ref.site}/{ref.path}", check_robots=True)
    info = (d or {}).get("jobPostingInfo")
    if not info:
        return None
    return Posting(
        ats="workday", url=info.get("externalUrl") or ref.url, title=info.get("title", "").strip(),
        location=info.get("location", ""), description=_text(info.get("jobDescription")),
        req_id=info.get("jobReqId") or ref.job_id, posted_date=parse_posted(info.get("startDate") or info.get("postedOn")),
        employment_type=info.get("timeType", ""), company=((d.get("hiringOrganization") or {}).get("name", "")),
        active=info.get("canApply", True) is not False,
        evidence=[f"listed on Workday career site '{ref.site}' ({ref.host}), req {info.get('jobReqId')}"])


# ---------------- whole board (to find a vacancy discovered elsewhere) ----------------
def list_board(board: AtsRef, title_hint: str = "") -> list:
    """Postings on a board. Workday/SmartRecruiters are searched by title instead of listed in full."""
    if board.ats == "greenhouse":
        d = http_client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board.board}/jobs?content=true") or {}
        return [_gh(j, board.board) for j in d.get("jobs") or []]
    if board.ats == "lever":
        d = http_client.get_json(f"https://api.lever.co/v0/postings/{board.board}?mode=json") or []
        return [_lever(j, board.board) for j in d]
    if board.ats == "ashby":
        return [_ashby(j, board.board) for j in _ashby_board(board.board)]
    if board.ats == "smartrecruiters":
        from urllib.parse import quote
        d = http_client.get_json(f"https://api.smartrecruiters.com/v1/companies/{board.board}/postings?limit=100&q={quote(title_hint)}") or {}
        return [_sr(j, board.board) for j in d.get("content") or []]
    if board.ats == "workday" and board.host and board.site:
        d = http_client.post_json(f"https://{board.host}/wday/cxs/{board.board}/{board.site}/jobs",
                                  {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": title_hint},
                                  check_robots=True) or {}
        out = []
        for j in d.get("jobPostings") or []:
            path = (j.get("externalPath") or "").lstrip("/")
            rid = re.search(r"_([A-Za-z0-9-]+)$", path)
            out.append(Posting(ats="workday", url=f"https://{board.host}/{board.site}/{path}", title=j.get("title", ""),
                               location=j.get("locationsText", ""), req_id=rid.group(1) if rid else "", active=True,
                               evidence=[f"found via Workday career-site search on {board.host}"]))
        return out
    return []


def detail_ref(board: AtsRef, p: Posting) -> AtsRef:
    """Single-vacancy reference for a posting found by list_board (to fetch its full description)."""
    if board.ats == "workday":
        path = p.url.split(f"/{board.site}/", 1)[-1]
        return AtsRef("workday", board.board, p.req_id, site=board.site, host=board.host, path=path, url=p.url)
    return AtsRef(board.ats, board.board, p.req_id, url=p.url)


# ---------------- official-site vacancy pages ----------------
def _iter_ld(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_ld(x)
    elif isinstance(obj, dict):
        yield obj
        yield from _iter_ld(obj.get("@graph", []))


def _ld_location(jp):
    locs = jp.get("jobLocation") or []
    out = []
    for loc in locs if isinstance(locs, list) else [locs]:
        a = (loc or {}).get("address") or {}
        if isinstance(a, dict):
            country = a.get("addressCountry")
            country = country.get("name") if isinstance(country, dict) else country
            out.append(", ".join(filter(None, [a.get("addressLocality"), a.get("addressRegion"), country])))
    return "; ".join(filter(None, out))


def parse_jsonld_posting(page_html: str, url: str, today: date | None = None):
    """Posting from schema.org JobPosting markup. active=True only with a future validThrough."""
    today = today or date.today()
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html or ""):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for jp in _iter_ld(data):
            types = jp.get("@type")
            if "JobPosting" not in (types if isinstance(types, list) else [types]):
                continue
            valid = parse_posted(jp.get("validThrough"))
            ident = jp.get("identifier")
            ident = ident.get("value", "") if isinstance(ident, dict) else (ident or "")
            org = jp.get("hiringOrganization") or {}
            closed = bool(CLOSED_MARKERS.search(http_client.html_to_text(page_html)))
            if valid is None:
                active, ev = None, "JobPosting markup has no validThrough date"
            elif valid < today:
                active, ev = False, f"JobPosting validThrough {valid} has passed"
            else:
                active, ev = True, f"JobPosting markup valid through {valid}"
            if closed:
                active, ev = False, "page states the vacancy is closed"
            emp = jp.get("employmentType", "")
            return Posting(
                ats="official-site", url=url, title=str(jp.get("title", "")).strip(), location=_ld_location(jp),
                description=_text(jp.get("description")), req_id=str(ident), posted_date=parse_posted(jp.get("datePosted")),
                employment_type=", ".join(emp) if isinstance(emp, list) else emp,
                company=org.get("name", "") if isinstance(org, dict) else "",
                remote=jp.get("jobLocationType") == "TELECOMMUTE", active=active, evidence=[ev],
                valid_through=valid.isoformat() if valid else "")
    return None


def fetch_official_page_posting(url: str):
    r = http_client.get_page(url)
    if r.status_code in (404, 410):
        return Posting(ats="official-site", url=url, title="", active=False, evidence=[f"official vacancy page returns HTTP {r.status_code}"])
    if r.status_code != 200:
        return None
    return parse_jsonld_posting(r.text, r.url)
