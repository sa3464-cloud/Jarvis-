"""JARVIS local Stage 2 server and read-only graph API."""
from __future__ import annotations
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import runpy
from secrets import token_urlsafe
import sys

AGENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = AGENT_DIR.parent
UI_DIR = PROJECT_DIR / "ui"
sys.path.insert(0, str(AGENT_DIR))
from data import (DEMO_MODE, DEMO_ROOT, elevenlabs_status, gmail_status, load_sources,
                  read_gmail_inbox, start_gmail_authorization, synthesize_elevenlabs)
from vault import build_index, print_report
from tools import choose_tool, run_local
from model import status as model_status

HOST = "127.0.0.1"
PORT = 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/graph.js": ("graph.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def build_payload(loaded: dict, index: dict, profile: dict) -> dict:
    records = index["records"]
    excerpt_by_path = {item["path"]: item for item in index["citations"]}
    degree = [0] * len(records)
    edges = []
    for source_i, target_i in index["edges"]:
        degree[source_i] += 1
        degree[target_i] += 1
        edges.append({"source": records[source_i]["id"], "target": records[target_i]["id"]})
    notes = []
    for i, record in enumerate(records):
        excerpt = excerpt_by_path.get(record["path"], {})
        notes.append({
            "id": record["id"], "title": record["title"], "type": record["kind"],
            "source": record["source"], "path": record["path"],
            "line": excerpt.get("line", 1), "excerpt": excerpt.get("excerpt", ""),
            "degree": degree[i],
        })
    hubs = []
    by_path = {record["path"]: record for record in records}
    for count, title, path in index["hubs"]:
        record = by_path.get(path)
        if record:
            hubs.append({"id": record["id"], "title": title, "path": path, "degree": count})
    return {
        "mode": loaded["mode"],
        "model": model_status(),
        "gmail": gmail_status(profile.get("gmailAccount", "")),
        "voice": elevenlabs_status(),
        "refreshed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": notes, "edges": edges, "countsByType": index["counts_by_type"], "hubs": hubs,
        "unresolved": index["unresolved"], "ambiguous": index["ambiguous"],
        "skipped": loaded["skipped"], "failures": loaded["failures"],
        "pdfExtractorAvailable": loaded["pdf_extractor_available"],
    }


def load_profile() -> dict:
    """Load confirmed profile configuration separately from indexed source files."""
    path = PROJECT_DIR / "PROFILE.md"
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {"content": "", "name": "there", "gmailAccount": ""}
    name = "there"
    gmail_account = ""
    for line in content.splitlines():
        if line.strip().casefold().startswith("- preferred name:"):
            name = line.partition(":")[2].strip().rstrip(".") or "there"
        if line.strip().casefold().startswith("- gmail account:"):
            gmail_account = line.partition(":")[2].strip()
    return {"content": content, "name": name, "gmailAccount": gmail_account}


class Handler(BaseHTTPRequestHandler):
    server_version = "JARVISLocal/0.2"

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")

    def _valid_request(self) -> bool:
        host = self.headers.get("Host", "").casefold()
        if host not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and origin.casefold() not in {f"http://{item}" for item in ALLOWED_HOSTS}:
            return False
        return True

    def _send(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._valid_request():
            self._send(403, "text/plain; charset=utf-8", b"Forbidden")
            return
        path = self.path.partition("?")[0]
        if path == "/api/index":
            body = json.dumps(self.server.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path == "/api/gmail/status":
            result = gmail_status(self.server.profile.get("gmailAccount", ""))
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path == "/api/voice/status":
            body = json.dumps(elevenlabs_status(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        item = STATIC_FILES.get(path)
        if item:
            filename, content_type = item
            try:
                body = (UI_DIR / filename).read_bytes()
            except OSError:
                self._send(404, "text/plain; charset=utf-8", b"Not found")
                return
            self._send(200, content_type, body)
            return
        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self):
        if not self._valid_request():
            self._send(403, "text/plain; charset=utf-8", b"Forbidden")
            return
        path = self.path.partition("?")[0]
        if path == "/api/voice/speak":
            self._serve_voice()
            return
        if path == "/api/gmail/connect":
            try:
                account = self.server.profile.get("gmailAccount", "")
                if not account:
                    raise RuntimeError("No Gmail account is configured in PROFILE.md.")
                result = {"url": start_gmail_authorization(account)}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(result).encode("utf-8"))
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self._send(409, "application/json; charset=utf-8", body)
            return
        if path != "/api/chat":
            self._send(404, "text/plain; charset=utf-8", b"Not found")
            return
        if self.headers.get_content_type() != "application/json":
            self._send(415, "text/plain; charset=utf-8", b"Expected application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > 12000:
            self._send(413, "text/plain; charset=utf-8", b"Request size must be under 12 KB")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            sid, text = payload.get("sessionId", ""), payload.get("text", "")
            if not isinstance(sid, str) or not re.fullmatch(r"[a-fA-F0-9-]{16,64}", sid):
                raise ValueError("invalid session id")
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise ValueError("message must be 1 to 4000 characters")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError):
            self._send(400, "text/plain; charset=utf-8", b"Invalid chat request")
            return
        sessions = self.server.sessions
        history = sessions.setdefault(sid, [])
        inbox_data = None
        if choose_tool(text.strip()) == "read_inbox" and gmail_status(self.server.profile.get("gmailAccount", "")).get("connected"):
            try:
                inbox_data = read_gmail_inbox(self.server.profile["gmailAccount"], self.server.loaded["records"])
            except Exception:
                inbox_data = None
        result = run_local(text.strip(), self.server.loaded["records"], history[-10:],
                           self.server.profile["name"], inbox_data)
        is_gmail_reply = result.get("card", {}).get("kind") == "inbox"
        voice = elevenlabs_status()
        request_id = token_urlsafe(24)
        allowed = voice["configured"] and (not is_gmail_reply or voice["emailTtsAllowed"])
        self.server.voice_requests[request_id] = {
            "text": result["spoken"], "allowed": allowed, "gmail": is_gmail_reply,
            "reason": ("Gmail-derived text stays on this computer. Browser voice will read it locally."
                       if is_gmail_reply and not voice["emailTtsAllowed"] else voice["detail"]),
            "audio": None,
        }
        while len(self.server.voice_requests) > 50:
            self.server.voice_requests.pop(next(iter(self.server.voice_requests)))
        result["voice"] = {
            "requestId": request_id if allowed else None,
            "provider": "ElevenLabs" if allowed else "Browser voice",
            "reason": self.server.voice_requests[request_id]["reason"],
        }
        history.extend([
            {"role": "user", "text": text.strip()},
            {"role": "assistant", "text": result["spoken"], "card": result["card"]["title"]},
        ])
        del history[:-10]
        while len(sessions) > 200:
            sessions.pop(next(iter(sessions)))
        body = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body)

    def _serve_voice(self):
        if self.headers.get_content_type() != "application/json":
            self._send(415, "text/plain; charset=utf-8", b"Expected application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 2048:
                raise ValueError
            request_id = json.loads(self.rfile.read(length).decode("utf-8")).get("requestId", "")
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", request_id):
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, AttributeError):
            self._send(400, "text/plain; charset=utf-8", b"Invalid voice request")
            return
        entry = self.server.voice_requests.get(request_id)
        if not entry or not entry["allowed"]:
            self._send(403, "text/plain; charset=utf-8", b"ElevenLabs voice is not available for this reply")
            return
        try:
            if entry["audio"] is None:
                entry["audio"] = synthesize_elevenlabs(entry["text"])
            audio, content_type = entry["audio"]
            self._send(200, content_type, audio)
        except Exception:
            self._send(502, "text/plain; charset=utf-8", b"ElevenLabs voice request failed")

    def do_HEAD(self):
        if not self._valid_request():
            self._send(403, "text/plain; charset=utf-8", b"")
            return
        self._send(404, "text/plain; charset=utf-8", b"")

    def log_message(self, fmt, *args):
        print(f"[http] {args[0] if args else ''}")


def main():
    if DEMO_MODE and not any(DEMO_ROOT.rglob("*.md")):
        runpy.run_path(str(PROJECT_DIR / "data" / "generate_demo.py"), run_name="__main__")
    loaded = load_sources()
    index = build_index(loaded["records"])
    print_report(index, loaded)
    if not DEMO_MODE and not loaded["records"]:
        print("No approved source records. Set JARVIS_APPROVED_ROOTS to exact, approved folder paths.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.loaded = loaded
    server.profile = load_profile()
    server.payload = build_payload(loaded, index, server.profile)
    server.sessions = {}
    server.voice_requests = {}
    print(f"JARVIS is ready at http://127.0.0.1:{PORT}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nJARVIS stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
