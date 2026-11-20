"""Local OAuth configuration and DPAPI token storage; network access stays in data.py."""
from __future__ import annotations
import base64
import ctypes
import ctypes.wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import urlencode, urlparse, parse_qs

PROJECT_DIR = Path(__file__).resolve().parents[1]
CLIENT_FILE = PROJECT_DIR / "secrets" / "google_oauth_client.json"
TOKEN_FILE = PROJECT_DIR / "secrets" / "gmail_token.bin"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
FLOW = {}
FLOW_LOCK = threading.Lock()


def read_client():
    with CLIENT_FILE.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    client = data.get("installed")
    if not client or not client.get("client_id"):
        raise RuntimeError("Use a downloaded Desktop app OAuth JSON client.")
    return client


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure token storage is supported on Windows only.")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    source = ctypes.create_string_buffer(data)
    in_blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    out_blob = Blob()
    crypt = ctypes.windll.crypt32
    if protect:
        crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.POINTER(Blob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = crypt.CryptProtectData(ctypes.byref(in_blob), "JARVIS Gmail token", None, None, None, 1, ctypes.byref(out_blob))
    else:
        crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = crypt.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 1, ctypes.byref(out_blob))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel = ctypes.windll.kernel32
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def save_token(token: dict):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_bytes(_dpapi(json.dumps(token, separators=(",", ":")).encode("utf-8"), True))


def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(_dpapi(TOKEN_FILE.read_bytes(), False).decode("utf-8"))
    except Exception:
        return None


def status(account: str) -> dict:
    token = load_token()
    configured = CLIENT_FILE.is_file()
    return {"account": account, "connected": bool(token and token.get("refresh_token")),
            "configured": configured, "access": "read-only",
            "detail": ("Connected read-only; token encrypted for this Windows user." if token else
                ("Client file ready; authorize the account in JARVIS." if configured else
                 "Save the downloaded Desktop client JSON to jarvis/secrets/google_oauth_client.json."))}


class OAuthCallback(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        with FLOW_LOCK:
            flow = dict(FLOW)
        state = query.get("state", [""])[0]
        code = query.get("code", [""])[0]
        error = query.get("error", [""])[0]
        message = "Authorization was not completed. Return to JARVIS."
        if flow and state == flow["state"] and code and not error:
            try:
                token = flow["complete"](flow, code)
                save_token(token)
                message = "Read-only Gmail authorization is connected. Return to JARVIS."
                with FLOW_LOCK:
                    FLOW["result"] = "connected"
            except Exception:
                with FLOW_LOCK:
                    FLOW["result"] = "error"
                message = "JARVIS could not finish authorization. Check the local setup and try again."
        else:
            with FLOW_LOCK:
                FLOW["result"] = "error"
        body = ("<!doctype html><meta charset=utf-8><title>JARVIS Gmail</title>"
                "<style>body{font:16px Segoe UI,sans-serif;background:#091116;color:#d6e7ec;padding:3rem}</style>"
                "<h1>JARVIS</h1><p>" + message + "</p>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        threading.Thread(target=self._stop_server, daemon=True).start()

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()

    def log_message(self, _format, *_args):
        return


def start_authorization(account: str, complete_callback) -> str:
    client = read_client()
    with FLOW_LOCK:
        if FLOW.get("result") == "waiting":
            raise RuntimeError("A Gmail authorization is already in progress.")
    callback = HTTPServer(("127.0.0.1", 0), OAuthCallback)
    redirect_uri = "http://127.0.0.1:" + str(callback.server_address[1])
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    with FLOW_LOCK:
        FLOW.clear()
        FLOW.update({"state": state, "verifier": verifier, "redirect": redirect_uri,
                     "client": client, "account": account, "result": "waiting",
                     "complete": complete_callback, "callback": callback})
    threading.Thread(target=callback.serve_forever, daemon=True).start()
    params = {"client_id": client["client_id"], "redirect_uri": redirect_uri,
              "response_type": "code", "scope": SCOPE, "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256",
              "access_type": "offline", "prompt": "consent", "login_hint": account}
    return AUTH_URL + "?" + urlencode(params)
