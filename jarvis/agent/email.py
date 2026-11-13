"""Connect a read-only inbox for one local session; no credentials are persisted."""
import argparse
import json
import sys
import html
from email.utils import parseaddr

from . import data


def spoken_summary(messages):
    if not messages:
        return 'There are no unread messages in your inbox.'
    lines = [f'Here are {len(messages)} unread inbox messages.']
    for message in messages:
        sender = parseaddr(message['from'])[0] or parseaddr(message['from'])[1] or 'an unknown sender'
        subject = ' '.join(html.unescape(message['subject']).split())[:200]
        lines.append(f'From {sender[:100]}. Subject: {subject}.')
    return ' '.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', help='Path to downloaded Google Desktop OAuth JSON')
    parser.add_argument('--limit', type=int, default=10, choices=range(1, 26), metavar='1-25')
    args = parser.parse_args()
    try:
        token, address = data.connect_email(args.client)
        messages = data.read_inbox(token, args.limit)
        print(f'Connected read-only: {address}. Showing {len(messages)} unread inbox messages.')
        # JSON escapes terminal control characters supplied by untrusted email.
        print(json.dumps({'messages': messages, 'truncated_to': args.limit}, indent=2, ensure_ascii=True))
        print('Session ended. No token or messages saved. Sign in again on the next run.')
    except (RuntimeError, ValueError) as error:
        print(f'Email unavailable: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nSign-in cancelled.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
