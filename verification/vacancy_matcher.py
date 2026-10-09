"""Exact vacancy matching. Similar titles are not enough: normalised titles must be identical,
locations must be compatible and requisition IDs, when both sides have one, must be equal."""
import re

from filters import INDIA_PLACES

_SYNONYMS = {"bangalore": "bengaluru", "gurgaon": "gurugram", "bombay": "mumbai", "cochin": "kochi",
             "trivandrum": "thiruvananthapuram", "mysore": "mysuru", "vizag": "visakhapatnam", "new delhi": "delhi",
             "navi mumbai": "mumbai"}
_STATES_AND_COUNTRY = {"india", "karnataka", "maharashtra", "telangana", "tamil nadu", "haryana", "uttar pradesh",
                       "west bengal", "gujarat", "kerala", "rajasthan", "andhra pradesh", "odisha", "madhya pradesh",
                       "punjab", "goa", "keralam", "assam", "bihar", "jharkhand", "chhattisgarh", "uttarakhand",
                       "himachal pradesh", "jammu and kashmir", "jammu", "ladakh", "tripura", "meghalaya", "manipur",
                       "mizoram", "nagaland", "sikkim", "arunachal pradesh", "puducherry", "pondicherry", "orissa"}
_CITIES = [p for p in INDIA_PLACES if p not in _STATES_AND_COUNTRY]
_CITY_RX = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _CITIES), key=len, reverse=True)) + r")\b", re.I)
_REMOTEISH = re.compile(r"\b(remote|anywhere|work from home|wfh|india)\b", re.I)
_ABBREV = {"jr": "junior", "sr": "senior", "assoc": "associate", "engg": "engineer", "grad": "graduate"}
_LOC_SUFFIX = re.compile(r"\s[-–|,]\s*[^-–|,]*\b(remote|hybrid|onsite|on-site|india|" + "|".join(map(re.escape, _CITIES)) + r")\b.*$", re.I)


def norm_title(t: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (t or "").lower()).replace("&", " and ")
    t = _LOC_SUFFIX.sub("", t)
    words = [_ABBREV.get(w, w) for w in re.sub(r"[^a-z0-9]+", " ", t).split()]
    return " ".join(words)


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def cities(loc: str) -> set:
    return {_SYNONYMS.get(c.lower(), c.lower()) for c in _CITY_RX.findall(loc or "")}


def locations_compatible(a: str, b: str, b_remote=False) -> bool:
    ca, cb = cities(a), cities(b)
    if ca and cb:
        return bool(ca & cb)
    india_or_remote = lambda s: bool(_REMOTEISH.search(s or "") or cities(s))
    return india_or_remote(a) and (b_remote or india_or_remote(b))


def match(job, posting) -> tuple:
    if job.req_id and posting.req_id and norm_id(job.req_id) != norm_id(posting.req_id):
        return False, f"requisition ID differs ({job.req_id} vs {posting.req_id})"
    if norm_title(job.title) != norm_title(posting.title):
        return False, f"title differs ('{job.title}' vs '{posting.title}')"
    if not locations_compatible(job.location, posting.location, posting.remote):
        return False, f"location differs ('{job.location}' vs '{posting.location}')"
    how = "requisition ID, title and location" if job.req_id and posting.req_id else "title and location"
    return True, f"{how} match employer posting '{posting.title}' ({posting.location or 'location n/a'})"


def find_in_board(job, postings) -> tuple:
    hits = [p for p in postings if match(job, p)[0]]
    if len(hits) == 1:
        return hits[0], match(job, hits[0])[1]
    if not hits:
        return None, "no vacancy with the same title and location on the employer's ATS board"
    return None, f"ambiguous: {len(hits)} vacancies on the employer's board match title and location"
