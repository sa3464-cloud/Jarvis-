"""The only module allowed to read user source folders. Never writes to them."""
import os
import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEMO = os.environ.get('JARVIS_DEMO', '1') != '0'
MAX_BYTES = 2 * 1024 * 1024
SKIP = {'.git', 'node_modules', '.venv', '__pycache__'}


def sources():
    """Return text records and explicit warnings; source folders are read-only."""
    folders = [ROOT / 'data' / 'demo'] if DEMO else [
        Path(p).expanduser() for p in os.environ.get('JARVIS_FOLDERS', '').split(os.pathsep) if p
    ]
    records, warnings = [], []
    if not folders:
        warnings.append('Real mode has no folders configured. Set JARVIS_FOLDERS.')
    for index, folder in enumerate(folders):
        if not folder.is_dir():
            warnings.append(f'Folder unavailable: {folder}')
            continue
        for current, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not (Path(current) / d).is_symlink())
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix.lower() not in {'.md', '.txt', '.pdf'} or path.is_symlink():
                    continue
                try:
                    if path.stat().st_size > MAX_BYTES:
                        warnings.append(f'Skipped file over 2 MB: {name}')
                        continue
                    relative = path.relative_to(folder).as_posix()
                    if path.suffix.lower() == '.pdf':
                        # Reliable extraction of arbitrary PDFs needs a PDF engine.
                        # Index the filename without pretending its contents were read.
                        body = ''
                        warnings.append(f'PDF indexed by filename only; text extraction unavailable: {relative}')
                    else:
                        body = path.read_text(encoding='utf-8-sig', errors='replace')
                    records.append({'id': f'{index}/{relative}', 'file': relative,
                                    'title': path.stem, 'text': body,
                                    'format': path.suffix.lower()[1:]})
                except OSError as error:
                    warnings.append(f'Cannot read {name}: {error}')
    return records, warnings


def status():
    return {'demo': DEMO, 'source': 'Invented demo fixtures' if DEMO else 'Configured read-only folders'}


def profile():
    """Load the configured user profile; never load keys into model context."""
    path = ROOT / 'CLAUDE.md'
    return path.read_text(encoding='utf-8')[:6000] if path.is_file() else 'Preferred name: Seth.'


GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'


def _google_json(url, token=None, form=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    body = urlencode(form).encode() if form is not None else None
    request = Request(url, data=body, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        # Never expose an OAuth code, client secret, token, or message body in errors.
        raise RuntimeError(f'Google returned HTTP {error.code}. Check API access, consent, and NJIT account policy.') from None
    except (URLError, TimeoutError):
        raise RuntimeError('Google could not be reached. Check your network and try again.') from None


def connect_email(client_path=None, expected_email='sa3464@njit.edu', timeout=180):
    """Interactive desktop OAuth. Tokens exist in process memory only."""
    if DEMO:
        raise RuntimeError('Demo mode does not access real email. Set JARVIS_DEMO=0 to opt in.')
    path = Path(client_path) if client_path else ROOT / '.secrets' / 'google-oauth.json'
    if not path.is_file():
        raise RuntimeError('Missing Google Desktop OAuth client file. See jarvis/README.md, Email connection.')
    try:
        client = json.loads(path.read_text(encoding='utf-8-sig'))['installed']
        client_id = client['client_id']
        client_secret = client.get('client_secret', '')
        if not isinstance(client_id, str) or not client_id.endswith('.apps.googleusercontent.com'):
            raise ValueError('Invalid client ID')
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('Invalid client file. Download OAuth credentials of type Desktop app.') from None

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Default access logs would disclose the authorization code.

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            valid = (parsed.path == '/oauth/callback' and
                     secrets.compare_digest(query.get('state', [''])[0], state))
            if not valid:
                self.send_error(400, 'Invalid sign-in callback')
                return
            if 'error' in query:
                result['error'] = 'Google sign-in was declined or blocked by your organization.'
            elif query.get('code'):
                result['code'] = query['code'][0]
            else:
                self.send_error(400, 'Missing authorization code')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(b'Sign-in response received. Return to the JARVIS terminal to check the connection.')

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = 1
        redirect = f'http://127.0.0.1:{server.server_port}/oauth/callback'
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client_id, 'redirect_uri': redirect, 'response_type': 'code',
            'scope': GMAIL_SCOPE, 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256', 'access_type': 'online',
            'prompt': 'consent', 'login_hint': expected_email,
        })
        print('Sign in to Google in your browser. Requesting read-only Gmail access.')
        if not webbrowser.open(url):
            print('Open this sign-in URL in your browser:\n' + url)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if result.get('error'):
        raise RuntimeError(result['error'])
    if not result.get('code'):
        raise RuntimeError('Sign-in timed out. Run the command again when ready.')
    token_data = _google_json('https://oauth2.googleapis.com/token', form={
        'client_id': client_id, 'client_secret': client_secret, 'code': result['code'],
        'code_verifier': verifier, 'redirect_uri': redirect, 'grant_type': 'authorization_code',
    })
    if set(token_data.get('scope', '').split()) != {GMAIL_SCOPE}:
        raise RuntimeError('Unexpected granted permissions. Connection refused; review Google account app access.')
    token = token_data.get('access_token')
    if not token:
        raise RuntimeError('Google did not return an access token.')
    profile = _google_json('https://gmail.googleapis.com/gmail/v1/users/me/profile', token=token)
    if profile.get('emailAddress', '').casefold() != expected_email.casefold():
        raise RuntimeError('Signed into a different account. Run again and select your NJIT account.')
    return token, profile['emailAddress']


def read_inbox(token, limit=10):
    """Only GET endpoints; reading does not mark messages read. No mail is stored."""
    if DEMO:
        raise RuntimeError('Real inbox access is disabled in demo mode.')
    if not 1 <= limit <= 25:
        raise ValueError('Inbox limit must be between 1 and 25.')
    base = 'https://gmail.googleapis.com/gmail/v1/users/me/'
    listing = _google_json(base + 'messages?' + urlencode({
        'labelIds': 'INBOX', 'q': 'is:unread', 'maxResults': limit,
    }), token=token)
    messages = []
    for item in listing.get('messages', []):
        message = _google_json(base + 'messages/' + quote(item['id'], safe='') +
                               '?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date', token=token)
        headers = {h['name'].casefold(): h['value'] for h in message.get('payload', {}).get('headers', [])}
        messages.append({'id': message['id'], 'from': headers.get('from', ''),
                         'subject': headers.get('subject', '(no subject)'),
                         'date': headers.get('date', ''), 'snippet': message.get('snippet', '')})
    return messages
