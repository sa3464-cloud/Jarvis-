"""Explicit command routing. Model replies and retrieved content never run actions."""
import ipaddress
import re
import webbrowser
from urllib.parse import urlsplit, urlunsplit

from . import conversation, data
from .email import spoken_summary

SITES = {'youtube': 'https://www.youtube.com', 'google': 'https://www.google.com',
         'gmail': 'https://mail.google.com', 'wikipedia': 'https://www.wikipedia.org',
         'github': 'https://github.com', 'chatgpt': 'https://chatgpt.com',
         'njit': 'https://www.njit.edu'}
PRIORITIES_QUESTION = 'What are your top priorities and fixed commitments today?'


def plan_day(question, history):
    candidates = [item['content'] for item in history if item['role'] == 'user'] + [question]
    goals = []
    for text in candidates:
        text = re.sub(r'^.*?\b(?:plan|organize|organise)(?: out)? (?:my|the|your) day[.!?\s:]*', '', text, flags=re.I)
        match = re.search(r'\b(?:priorit(?:y|ies)(?:\s+(?:is|are))?|(?:I\s+)?(?:need|have|want) to|tasks?\s*(?:are|:))\s*(.+)', text, re.I | re.S)
        if match:
            text = match.group(1)
        elif not history or text == question and history[-1].get('content') != PRIORITIES_QUESTION:
            continue
        text = re.split(r'\b(?:keep your response|reply in|answer in)\b', text, flags=re.I)[0]
        for goal in re.split(r'[,;\n]|\band then\b', text, flags=re.I):
            goal = re.sub(r'^\s*\d+[.)]\s*', '', goal).strip(' .!?')[:400]
            if goal and goal.casefold() not in {item.casefold() for item in goals}:
                goals.append(goal)
    if not goals:
        answer = PRIORITIES_QUESTION
    else:
        # Preserve the user's order except for explicitly urgent work. No invented
        # durations, appointments, extra tasks, or claim of persistent memory.
        goals.sort(key=lambda goal: not bool(re.search(r'\b(urgent|asap|due today|overdue)\b', goal, re.I)))
        goals = goals[:5]
        answer = 'Suggested plan — calendar not checked.\n\n' + '\n'.join(f'{i}. {goal}' for i, goal in enumerate(goals, 1))
        answer += '\n\nBased only on the priorities you supplied; no time slots have been booked.'
    return {'answer': answer, 'spoken': answer, 'model_missing': False, 'model': 'Day planner',
            'action': 'plan_day', 'sources': [], 'card': {'type': 'plan', 'calendar_checked': False, 'items': goals[:5]}}


def intent(question):
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError('Question must contain 1–4,000 characters.')
    text = question.strip()
    text = re.sub(r'^(?:hey\s+)?jarvis[,\s]+', '', text, flags=re.I)
    text = re.sub(r'^(?:please\s+|(?:can|could|would) you\s+)', '', text, flags=re.I)
    text = re.sub(r'\s+please[.!?]*$', '', text, flags=re.I).strip()
    if re.fullmatch(r'(?:read(?:\s+out|\s+aloud)?|check|show|summari[sz]e)(?: me)?(?: my| the)?(?: unread)? (?:e-?mails?|inbox|messages)(?: aloud| out loud)?[.!?]*', text, re.I):
        return 'read_inbox', None
    if re.match(r'^(?:plan|organize|organise)(?: out)? (?:my|the|your) day\b', text, re.I):
        return 'plan_day', None
    match = re.fullmatch(r'(?:open|visit|go to)(?: the website| website)?\s+(.+?)', text, re.I)
    if match:
        return 'open_website', website_url(match.group(1))
    return 'conversation', None


def website_url(value):
    value = value.strip().rstrip('.!?')
    if value.casefold() in SITES:
        return SITES[value.casefold()]
    if any(character.isspace() for character in value) or any(c in value for c in '\\<>"\''):
        raise ValueError('Name a known website or provide its full web address, such as https://example.com.')
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    if (parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or
            not host or '.' not in host or host.endswith(('.local', '.localhost', '.internal'))):
        raise ValueError('Only public HTTP or HTTPS websites can be opened.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Use a public website domain rather than an IP address.')
    host = host.encode('idna').decode('ascii')
    if not re.fullmatch(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+', host) or host.endswith('.localhost'):
        raise ValueError('Invalid website domain.')
    if parsed.port not in {None, 80, 443}:
        raise ValueError('Only standard web ports are supported.')
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def read_inbox():
    token, account = data.connect_email()
    messages = data.read_inbox(token, 5)
    spoken = spoken_summary(messages)
    return {'answer': spoken, 'spoken': spoken, 'model_missing': False,
            'model': 'Read-only Gmail', 'action': 'read_inbox', 'sources': [],
            'card': {'type': 'inbox', 'account': account, 'messages': messages}}


def execute(question, history=None):
    history = conversation.validated_history(history or [])
    action, target = intent(question)
    if action == 'conversation' and history and history[-1].get('role') == 'assistant' and history[-1].get('content') == PRIORITIES_QUESTION:
        action = 'plan_day'
    if action == 'read_inbox':
        return read_inbox()
    if action == 'open_website':
        opened = webbrowser.open(target, new=2)
        if not opened:
            raise RuntimeError('The browser could not be launched. Use the website link shown on screen.')
        text = f'I asked your browser to open {urlsplit(target).hostname}.'
        return {'answer': text, 'spoken': text, 'model_missing': False, 'model': 'Website command',
                'action': action, 'sources': [], 'card': {'type': 'website', 'url': target}}
    if action == 'plan_day':
        return plan_day(question, history)
    return {**conversation.answer(question, history), 'action': action}
