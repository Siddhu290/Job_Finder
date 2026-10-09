"""HTTP helpers: timeouts, retries with exponential backoff, robots.txt, job-board guard, secret redaction."""
import logging
import re
import time
import urllib.robotparser
from functools import wraps
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = "FresherDataJobFinder/1.0 (personal job search; manual applications only)"
TIMEOUT = (6, 25)  # connect, read

# Discovery-only sites. We never fetch them directly and never use them as an official apply URL.
JOB_BOARDS = {
    "linkedin.com", "naukri.com", "indeed.com", "indeed.co.in", "glassdoor.com", "glassdoor.co.in",
    "monster.com", "monsterindia.com", "foundit.in", "shine.com", "timesjobs.com", "instahyre.com",
    "wellfound.com", "angel.co", "internshala.com", "apna.co", "cutshort.io", "hirist.tech", "hirist.com",
    "iimjobs.com", "ziprecruiter.com", "simplyhired.com", "talent.com", "jooble.org", "careerbuilder.com",
    "freshersworld.com", "jobsora.com", "jobrapido.com", "adzuna.in", "adzuna.com", "bebee.com",
    "workindia.in", "hirect.in", "updazz.com", "jobted.in", "whatjobs.com", "learn4good.com",
    "builtin.com", "myinternships.in", "jobaaj.com", "jobgether.com", "glassdoor.co.uk", "dice.com", "remoteok.com", "weworkremotely.com", "remotive.com", "himalayas.app",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "crunchbase.com", "ambitionbox.com", "zaubacorp.com", "tofler.in", "economictimes.indiatimes.com",
}
# Reputable portals accepted as a discovery source. Anything else on JOB_BOARDS is a low-quality aggregator.
TRUSTED_PORTALS = {"linkedin.com", "naukri.com", "indeed.com", "indeed.co.in", "glassdoor.com", "glassdoor.co.in",
                   "foundit.in", "shine.com", "timesjobs.com", "instahyre.com", "wellfound.com", "cutshort.io", "hirist.tech", "hirist.com", "iimjobs.com"}
_TWO_LEVEL_SUFFIXES = {"co.in", "co.uk", "com.au", "co.jp", "com.sg", "com.br", "org.in", "net.in",
                       "firm.in", "gen.in", "ind.in", "ac.in", "gov.in", "co.nz", "com.my", "co.za"}


class RetryableError(Exception):
    pass


def registered_domain(url_or_host: str) -> str:
    """'https://careers.acme.co.in/x' -> 'acme.co.in'.
    ponytail: tiny public-suffix list; swap for tldextract if exotic TLDs show up."""
    host = urlparse(url_or_host).hostname if "//" in url_or_host else url_or_host
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    n = 3 if ".".join(parts[-2:]) in _TWO_LEVEL_SUFFIXES else 2
    return ".".join(parts[-n:])


def is_job_board(url: str) -> bool:
    return registered_domain(url) in JOB_BOARDS


def is_trusted_source(url: str, company: str = "") -> bool:
    """Discovery trust only (verification still applies): a recognised ATS, a reputable portal,
    or a site whose domain carries the employer's name (a likely company careers page)."""
    from verification.ats_verifier import parse_ats_url
    dom = registered_domain(url)
    if dom in TRUSTED_PORTALS or parse_ats_url(url):
        return True
    if dom in JOB_BOARDS:
        return False
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", (company or "").lower()).split() if len(w) >= 4]
    return bool(words) and words[0] in dom.replace("-", "")


def retry(attempts=4, base_delay=2.0, exceptions=(requests.Timeout, requests.ConnectionError, RetryableError)):
    """Exponential backoff: base, 2*base, 4*base ..."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            for i in range(attempts):
                try:
                    return fn(*a, **kw)
                except exceptions as e:
                    if i == attempts - 1:
                        raise
                    delay = base_delay * 2 ** i
                    log.warning("%s failed (%s); retry %d/%d in %.0fs", getattr(fn, "__name__", "call"), redact(str(e)), i + 1, attempts - 1, delay)
                    time.sleep(delay)
        return wrapper
    return deco


_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_robots: dict = {}
_last_hit: dict = {}


def _polite(host):
    # ponytail: 1 req/sec per host, in-process only
    wait = 1.0 - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def robots_allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = _session.get(base + "/robots.txt", timeout=TIMEOUT)
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp.disallow_all = True  # can't confirm permission -> don't fetch
        _robots[base] = rp
    return rp.can_fetch(USER_AGENT, url)


@retry()
def request(method, url, *, check_robots=False, **kw) -> requests.Response:
    """Returns the response for any status; retries on timeouts, connection errors, 429 and 5xx."""
    if is_job_board(url):
        raise PermissionError(f"refusing to fetch job-board URL {url}")
    if check_robots and not robots_allowed(url):
        raise PermissionError(f"robots.txt disallows {url}")
    _polite(urlparse(url).netloc)
    kw.setdefault("timeout", TIMEOUT)
    r = _session.request(method, url, **kw)
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableError(f"HTTP {r.status_code} from {urlparse(url).netloc}")
    return r


def get_json(url, **kw):
    """JSON body, or None on 404/410. Other 4xx raise."""
    r = request("GET", url, **kw)
    if r.status_code in (404, 410):
        return None
    r.raise_for_status()
    return r.json()


def post_json(url, payload, **kw):
    r = request("POST", url, json=payload, **kw)
    if r.status_code in (404, 410):
        return None
    r.raise_for_status()
    return r.json()


def get_page(url):
    """Public HTML page, robots.txt respected. Returns the Response (any status)."""
    return request("GET", url, check_robots=True, allow_redirects=True)


def html_to_text(html: str) -> str:
    import html as h
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    return re.sub(r"\s+", " ", h.unescape(re.sub(r"(?s)<[^>]+>", " ", html))).strip()


# --- secret redaction for logs and error messages ---
_SECRET_PATTERNS = [re.compile(r"(api_key=)[^&\s'\"]+", re.I),
                    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)]
_secret_values: set = set()


def register_secret(value: str):
    if value and len(value) >= 8:
        _secret_values.add(value)


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", text)
    for s in _secret_values:
        text = text.replace(s, "[REDACTED]")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


# For slow third-party APIs inside a time-limited run: one retry, short backoff (instead of 4 tries x 25 s).
request_quick = retry(attempts=2, base_delay=1.0)(request.__wrapped__)
QUICK_TIMEOUT = (5, 20)
