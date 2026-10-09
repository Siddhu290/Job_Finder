"""Configuration loading and startup validation. Never logs secret values."""
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    serpapi_key: str
    sheet_id: str
    worksheet: str
    credentials_path: Path
    timezone: str
    max_age_days: int
    serpapi_max_calls: int
    cache_dir: Path
    log_dir: Path


def load_config(require_serpapi=True, require_sheets=True) -> Config:
    load_dotenv(PROJECT_DIR / ".env")
    creds = os.getenv("GOOGLE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "credentials.json"
    creds_path = Path(creds)
    if not creds_path.is_absolute():
        creds_path = PROJECT_DIR / creds_path
    try:
        cfg = Config(
            serpapi_key=os.getenv("SERPAPI_KEY", "").strip(),
            sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
            worksheet=os.getenv("GOOGLE_WORKSHEET", "Jobs").strip() or "Jobs",
            credentials_path=creds_path,
            timezone=os.getenv("TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata",
            max_age_days=int(os.getenv("JOB_MAX_AGE_DAYS", "7")),
            serpapi_max_calls=int(os.getenv("SERPAPI_MAX_CALLS", "30")),
            cache_dir=Path(os.getenv("JOB_FINDER_DATA_DIR", PROJECT_DIR)) / ".cache",   # /tmp on Vercel
            log_dir=Path(os.getenv("JOB_FINDER_DATA_DIR", PROJECT_DIR)) / "logs",
        )
    except ValueError as e:
        raise ConfigError(f"JOB_MAX_AGE_DAYS and SERPAPI_MAX_CALLS must be integers ({e})") from None

    problems = []
    if require_serpapi and not cfg.serpapi_key:
        problems.append("SERPAPI_KEY is not set. Add it to .env (see .env.example); get a key at https://serpapi.com/manage-api-key")
    if require_sheets:
        if not cfg.sheet_id:
            problems.append("GOOGLE_SHEET_ID is not set in .env")
        problems += validate_credentials_file(cfg.credentials_path)
    if problems:
        raise ConfigError("Configuration problems:\n  - " + "\n  - ".join(problems))
    return cfg


def validate_credentials_file(path: Path) -> list:
    """Check the service-account file is present and well-formed without echoing its contents."""
    if not path.is_file():
        return [f"Google credentials file not found at {path}. Download a service-account JSON key and save it there, "
                "or set GOOGLE_CREDENTIALS in .env to its path"]
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return [f"{path} is not readable JSON"]
    missing = [k for k in ("type", "client_email", "private_key") if not data.get(k)]
    if data.get("type") != "service_account" or missing:
        return [f"{path} is not a service-account key (missing/invalid: {', '.join(missing) or 'type'})"]
    return []


def credentials_file_is_private(path: Path) -> bool:
    return not (path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))


def service_account_email(path: Path) -> str:
    """The client_email is not secret; it is what the user must share the sheet with."""
    try:
        return json.loads(path.read_text()).get("client_email", "")
    except (OSError, ValueError):
        return ""
