"""The sole gateway for source-file reads and personal source integrations."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from gmail import load_token, read_client, save_token, start_authorization, status as _gmail_status

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = PROJECT_ROOT / "data" / "demo"
MAX_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__"}
SECRET_NAME = re.compile(r"(^|[._-])(\.env|credentials?|secrets?|token|apikey|api_key|id_rsa)([._-]|$)", re.I)
ELEVENLABS_CONFIG = PROJECT_ROOT / "secrets" / "elevenlabs.env"

# JARVIS_DEMO is intentionally read in this file only; absent means safe demo mode.
DEMO_MODE = os.environ.get("JARVIS_DEMO", "1").strip() != "0"


def _configured_paths(variable: str) -> tuple[list[Path], list[str]]:
    paths, errors = [], []
    for item in os.environ.get(variable, "").split(os.pathsep):
        if not item.strip():
            continue
        try:
            paths.append(Path(item.strip()).expanduser().resolve(strict=True))
        except (OSError, RuntimeError):
            errors.append(f"configured path does not exist or cannot be resolved")
    return paths, errors


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _walk(root: Path, excluded: list[Path]):
    """Yield supported files, resolving symlinks and enforcing approved boundaries."""
    for parent, dirs, names in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        safe_dirs = []
        for name in sorted(dirs):
            candidate = parent_path / name
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if name in SKIP_DIRS or SECRET_NAME.search(name) or not _inside(resolved, root):
                continue
            if any(_inside(resolved, exclusion) for exclusion in excluded):
                continue
            safe_dirs.append(name)
        dirs[:] = safe_dirs
        for name in sorted(names):
            candidate = parent_path / name
            try:
                resolved = candidate.resolve(strict=True)
                if not _inside(resolved, root) or any(_inside(resolved, e) for e in excluded):
                    continue
                if resolved.is_file():
                    yield candidate, resolved
            except (OSError, RuntimeError):
                continue


def _read_text(path: Path, relative: str, source: str) -> dict:
    try:
        raw = path.stat().st_size
    except OSError as exc:
        return {"failure": relative, "reason": f"stat failed: {type(exc).__name__}"}
    if raw > MAX_BYTES:
        return {"skipped": relative, "reason": "over 2 MB"}
    if SECRET_NAME.search(path.name):
        return {"skipped": relative, "reason": "credential-like filename"}
    suffix = path.suffix.casefold()
    if suffix in {".md", ".txt"}:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                return {"failure": relative, "reason": f"text decode/read failed: {type(exc).__name__}"}
        except OSError as exc:
            return {"failure": relative, "reason": f"read failed: {type(exc).__name__}"}
    elif suffix == ".pdf":
        if importlib.util.find_spec("pypdf") is None:
            return {"skipped": relative, "reason": "PDF text extractor unavailable; install only after approval"}
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            return {"failure": relative, "reason": f"PDF extraction failed: {type(exc).__name__}"}
        if not text.strip():
            return {"failure": relative, "reason": "PDF contained no extractable text"}
    else:
        return {"skipped": relative, "reason": "unsupported file type"}
    title, kind = path.stem.replace("_", " "), "note"
    for line in text.splitlines()[:12]:
        if line.startswith("title:"):
            title = line.partition(":")[2].strip().strip("'\"") or title
        elif line.startswith("type:"):
            kind = line.partition(":")[2].strip().strip("'\"").casefold() or kind
    marker = re.search(r"<!-- fixture:([0-9a-f]+) -->", text)
    stable_id = marker.group(1) if marker else hashlib.sha256(f"{source}:{relative}".encode("utf-8")).hexdigest()[:12]
    return {"id": stable_id, "title": title, "kind": kind, "content": text, "path": relative,
            "source": source, "size": raw}


def load_sources() -> dict:
    """Return normalized records and diagnostics; never write to source roots."""
    records, skipped, failures = [], [], []
    excluded, exclude_errors = _configured_paths("JARVIS_EXCLUDED_PATHS")
    skipped.extend({"path": "JARVIS_EXCLUDED_PATHS", "reason": message} for message in exclude_errors)
    if DEMO_MODE:
        roots = [(DEMO_ROOT.resolve(), "demo")]
    else:
        approved, root_errors = _configured_paths("JARVIS_APPROVED_ROOTS")
        skipped.extend({"path": "JARVIS_APPROVED_ROOTS", "reason": message} for message in root_errors)
        roots = [(p, "approved") for p in approved if p.is_dir()]
    for root, source in roots:
        if not root.exists():
            continue
        for original, resolved in _walk(root, excluded):
            rel = original.relative_to(root).as_posix()
            result = _read_text(resolved, rel, source)
            if "title" in result:
                records.append(result)
            elif "skipped" in result:
                skipped.append(result)
            else:
                failures.append(result)
    records.sort(key=lambda r: (r["source"], r["path"].casefold()))
    return {"records": records, "skipped": skipped, "failures": failures,
            "mode": "DEMO" if DEMO_MODE else "APPROVED SOURCES",
            "pdf_extractor_available": importlib.util.find_spec("pypdf") is not None}


# Gmail OAuth and API calls live here so this remains the single personal-data gateway.
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"


def gmail_status(account: str) -> dict:
    return _gmail_status(account)


def _post_google_form(fields: dict) -> dict:
    request = Request(GMAIL_TOKEN_URL, data=urlencode(fields).encode("ascii"),
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _gmail_get(path: str, access_token: str) -> dict:
    request = Request(GMAIL_API_ROOT + path,
        headers={"Authorization": "Bearer " + access_token, "Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _complete_gmail_oauth(flow: dict, code: str) -> dict:
    client = flow["client"]
    token = _post_google_form({
        "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
        "code": code, "code_verifier": flow["verifier"],
        "grant_type": "authorization_code", "redirect_uri": flow["redirect"],
    })
    profile = _gmail_get("/profile", token.get("access_token", ""))
    if profile.get("emailAddress", "").casefold() != flow["account"].casefold():
        raise RuntimeError("Google authorized a different account than the configured Gmail address.")
    return token


def start_gmail_authorization(account: str) -> str:
    return start_authorization(account, _complete_gmail_oauth)


def _gmail_access_token() -> str:
    token = load_token()
    if not token or not token.get("refresh_token"):
        raise RuntimeError("Gmail is not connected. Authorize the configured account first.")
    client = read_client()
    fresh = _post_google_form({
        "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
        "refresh_token": token["refresh_token"], "grant_type": "refresh_token",
    })
    fresh["refresh_token"] = token["refresh_token"]
    save_token(fresh)
    return fresh["access_token"]


def _gmail_text_part(part: dict) -> str:
    import base64
    data = part.get("body", {}).get("data")
    if data:
        try:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
        except Exception:
            return ""
    return "".join(_gmail_text_part(child) for child in part.get("parts", []))


def read_gmail_inbox(account: str, records: list[dict], limit: int = 5) -> dict:
    if not gmail_status(account).get("connected"):
        raise RuntimeError("Gmail is disconnected. Complete read-only authorization first.")
    access = _gmail_access_token()
    query = urlencode({"maxResults": min(max(limit, 1), 5), "q": "in:inbox"})
    listing = _gmail_get("/messages?" + query, access)
    items = []
    for message in listing.get("messages", []):
        full = _gmail_get("/messages/" + message["id"] + "?format=full", access)
        headers = {h.get("name", "").casefold(): h.get("value", "")
                   for h in full.get("payload", {}).get("headers", [])}
        subject, sender = headers.get("subject", "(no subject)"), headers.get("from", "Unknown sender")
        snippet = full.get("snippet", "")
        body_text = _gmail_text_part(full.get("payload", {}))[:3000]
        action = re.search(r"\b(action required|please|must|submit|complete|reply|review)\b",
                           body_text, re.I)
        deadline = re.search(r"\b(20\d{2}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2})\b",
                             body_text, re.I)
        haystack = (subject + " " + snippet).casefold()
        related = [r["title"] for r in records
                   if any(word in haystack for word in r["title"].casefold().split() if len(word) > 3)]
        items.append({"title": subject, "from": sender, "snippet": snippet[:500],
                      "action": action.group(1) if action else "No explicit action detected",
                      "deadline": deadline.group(1) if deadline else None, "matchedSources": related[:3]})
    return {"items": items, "account": account}


# ElevenLabs is optional. Its key is read only from a local, git-ignored file.
# Gmail-derived responses remain local by default and are never sent to ElevenLabs.
def _elevenlabs_config() -> dict:
    if not ELEVENLABS_CONFIG.is_file():
        return {}
    values = {}
    try:
        for line in ELEVENLABS_CONFIG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().upper()] = value.strip().strip("\"'")
    except OSError:
        return {}
    return values


def elevenlabs_status() -> dict:
    config = _elevenlabs_config()
    configured = bool(config.get("ELEVENLABS_API_KEY") and config.get("ELEVENLABS_VOICE_ID"))
    return {
        "configured": configured,
        "provider": "ElevenLabs" if configured else "Browser voice fallback",
        "emailTtsAllowed": config.get("ELEVENLABS_ALLOW_EMAIL_TTS", "false").casefold() == "true",
        "detail": ("Configured locally. Gmail-derived replies stay local unless you explicitly opt in."
                   if configured else
                   "Add a new local ElevenLabs key and voice ID in secrets/elevenlabs.env."),
    }


def synthesize_elevenlabs(text: str) -> tuple[bytes, str]:
    """Return ElevenLabs MP3 bytes. Caller must ensure this text is approved for transmission."""
    config = _elevenlabs_config()
    key, voice_id = config.get("ELEVENLABS_API_KEY"), config.get("ELEVENLABS_VOICE_ID")
    if not key or not voice_id:
        raise RuntimeError("ElevenLabs is not configured locally.")
    payload = json.dumps({
        "text": text[:3000],
        "model_id": config.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode("utf-8")
    request = Request(
        "https://api.elevenlabs.io/v1/text-to-speech/" + quote(voice_id, safe=""),
        data=payload,
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return response.read(), response.headers.get_content_type() or "audio/mpeg"

