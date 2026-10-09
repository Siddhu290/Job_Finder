"""SerpApi budget control: per-run cap, monthly safety limit, confirmed vs estimated usage.

- Confirmed numbers come only from SerpApi's account endpoint (free; it does not consume a search).
- Estimated usage is the sum of this month's recorded runs (Runs tab), used when the provider can't be reached.
- The controller never switches API keys or otherwise works around a quota."""
import logging
import os
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)
SAFETY_MARGIN = 2   # leave a couple of searches for manual checks


@dataclass
class Budget:
    allowed: int                 # searches this run may use
    per_run: int
    monthly_limit: int
    confirmed_left: int | None   # from SerpApi, if reachable
    confirmed_used: int | None
    estimated_used: int | None   # from our own run records
    reason: str

    def as_dict(self):
        return self.__dict__.copy()


def account(api_key: str) -> dict:
    """SerpApi account info, or {} if unavailable. Free endpoint: does not count against the quota."""
    if not api_key:
        return {}
    try:
        r = requests.get("https://serpapi.com/account.json", params={"api_key": api_key}, timeout=8)
        return r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        return {}


def plan(per_run: int, monthly_limit: int, acct: dict, estimated_used: int | None) -> Budget:
    confirmed_left = acct.get("total_searches_left")
    confirmed_used = acct.get("this_month_usage")
    allowed, reason = per_run, f"per-run limit {per_run}"
    used = confirmed_used if confirmed_used is not None else estimated_used
    if monthly_limit and used is not None and monthly_limit - used < allowed:
        allowed = max(0, monthly_limit - used)
        reason = f"monthly safety limit {monthly_limit} ({'confirmed' if confirmed_used is not None else 'estimated'} used {used})"
    if confirmed_left is not None and confirmed_left - SAFETY_MARGIN < allowed:
        allowed = max(0, confirmed_left - SAFETY_MARGIN)
        reason = f"only {confirmed_left} searches left on the SerpApi account (keeping {SAFETY_MARGIN} spare)"
    return Budget(allowed, per_run, monthly_limit, confirmed_left, confirmed_used, estimated_used, reason)


def monthly_limit() -> int:
    try:
        return int(os.getenv("SERPAPI_MONTHLY_LIMIT", "250"))
    except ValueError:
        return 250
