"""Local assistant tools. External providers stay unavailable unless configured later."""
from __future__ import annotations
import re
from datetime import date

WORD = re.compile(r"[A-Za-z0-9']+")
STOP = {"about", "after", "again", "also", "are", "can", "could", "does", "find", "from",
        "have", "help", "into", "need", "please", "show", "tell", "that", "the", "this",
        "what", "when", "where", "which", "with", "would", "your", "my"}
DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _terms(text: str) -> list[str]:
    return [word.casefold() for word in WORD.findall(text) if len(word) > 1 and word.casefold() not in STOP]


def search_brain(query: str, records: list[dict], limit: int = 5) -> dict:
    terms = _terms(query)
    scored = []
    for record in records:
        title = record["title"].casefold()
        lines = record["content"].splitlines()
        body = " ".join(line for line in lines if not line.startswith("---") and not line.startswith("type:") and not line.startswith("title:")).casefold()
        score = sum(4 for term in terms if term in title) + sum(body.count(term) for term in terms)
        if score:
            line_no, excerpt = 1, ""
            for i, line in enumerate(lines, 1):
                if line.strip() and not line.startswith(("---", "type:", "title:", "<!--")):
                    if any(term in line.casefold() for term in terms):
                        line_no, excerpt = i, line.strip()
                        break
                    if not excerpt:
                        line_no, excerpt = i, line.strip()
            scored.append((score, record, line_no, excerpt))
    scored.sort(key=lambda row: (-row[0], row[1]["title"].casefold(), row[1]["path"].casefold()))
    items = [{"title": r["title"], "type": r["kind"], "path": r["path"], "line": n, "excerpt": excerpt}
             for _, r, n, excerpt in scored[:limit]]
    if not items:
        return {"spoken": "I couldn’t find a clear match in the indexed files.", "card": {
            "kind": "search", "title": "No matching indexed notes", "items": [],
            "detail": "The local fallback searches only approved indexed text. It does not infer missing course information."}}
    return {"spoken": "I found " + str(len(items)) + " relevant indexed " + ("file." if len(items) == 1 else "files."),
            "card": {"kind": "search", "title": "Search results", "items": items,
                     "detail": "Local keyword matching; citations point to the indexed source and line."}}


def _deadline(record: dict):
    match = DATE.search(record["content"])
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def plan_day(records: list[dict]) -> dict:
    candidates = [r for r in records if r["kind"] in {"assignment", "exam", "project"}]
    candidates.sort(key=lambda r: (_deadline(r) is None, _deadline(r) or date.max, r["kind"] != "assignment", r["title"].casefold()))
    items = []
    for record in candidates[:5]:
        due = _deadline(record)
        items.append({"title": record["title"], "type": record["kind"], "path": record["path"],
                      "due": due.isoformat() if due else None,
                      "nextStep": "Open the source and identify the next concrete task.",
                      "estimate": "About 25 minutes for a first work block; estimate only."})
    answer = "Here’s a short plan based on the indexed assignments, exams, and projects."
    if items:
        answer += " I don’t know your availability, so this is an ordered task list, not a calendar schedule."
    else:
        answer = "I don’t have indexed assignments, exams, or projects to plan from yet."
    return {"spoken": answer, "card": {"kind": "plan", "title": "Suggested study plan", "items": items,
            "detail": "Ordered using source dates when present. No free time or overdue status was assumed."}}


def brief_me(records: list[dict]) -> dict:
    upcoming = []
    for record in records:
        if record["kind"] in {"assignment", "exam"}:
            due = _deadline(record)
            if due:
                upcoming.append({"title": record["title"], "type": record["kind"], "path": record["path"],
                                 "due": due.isoformat()})
    upcoming.sort(key=lambda item: item["due"])
    return {"spoken": "This briefing is incomplete because calendar and Gmail are not connected.",
            "card": {"kind": "briefing", "title": "Briefing · incomplete", "items": upcoming[:5],
                     "detail": "Shows dated assignments and exams in the index only. No calendar or inbox was checked."}}


def unavailable(tool: str) -> dict:
    messages = {
        "research_web": ("Web research is unavailable because no search provider is configured.",
                         "No external lookup was made."),
        "read_inbox": ("Gmail is disconnected. I did not read your inbox.",
                       "Read-only Gmail support stays disconnected until you explicitly approve and configure access."),
        "remember": ("Memory saving is not available in this stage.",
                     "Memory review and approved writes are added in Stage 5."),
    }
    spoken, detail = messages[tool]
    return {"spoken": spoken, "card": {"kind": "status", "title": tool.replace("_", " ").title(),
                                        "items": [], "detail": detail}}


def choose_tool(text: str) -> str | None:
    value = text.casefold()
    if any(word in value for word in ("remember", "save this", "save that", "memory")):
        return "remember"
    if any(word in value for word in ("gmail", "inbox", "email", "unread message")):
        return "read_inbox"
    if any(word in value for word in ("research", "look up", "latest", "current information", "web search")):
        return "research_web"
    if any(word in value for word in ("brief me", "briefing", "what's today", "what is today")):
        return "brief_me"
    if any(word in value for word in ("plan my day", "study plan", "plan today", "daily plan", "organize my assignments")):
        return "plan_day"
    if any(word in value for word in ("search", "find", "notes", "syllabus", "assignment", "course", "project", "exam")):
        return "search_brain"
    return None


def run_local(text: str, records: list[dict], history: list[dict], name: str = "Seth",
              inbox_data: dict | None = None) -> dict:
    """Explicitly model-free command routing and conversational fallback."""
    tool = choose_tool(text)
    if tool == "search_brain":
        return search_brain(text, records)
    if tool == "plan_day":
        return plan_day(records)
    if tool == "brief_me":
        return brief_me(records)
    if tool == "read_inbox":
        if inbox_data is None:
            return unavailable(tool)
        items = inbox_data.get("items", [])
        return {"spoken": ("I found " + str(len(items)) + " recent inbox messages for the configured account."
                           if items else "There are no inbox messages in the returned sample."),
                "card": {"kind": "inbox", "title": "Recent inbox · read-only", "items": items,
                         "detail": "Read from " + inbox_data.get("account", "configured Gmail") +
                                   ". Action and deadline labels are keyword hints, not verified commitments."}}
    if tool in {"research_web", "remember"}:
        return unavailable(tool)
    normalized = text.strip().casefold().strip(" .!?")
    if normalized in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "can you hear me", "are you there"}:
        return {"spoken": "Hi " + name + ". I’m here and ready to help with the indexed material. What are you working on?",
                "card": {"kind": "conversation", "title": "Ready", "items": [],
                         "detail": "Local conversational response. Model unavailable; open-ended reasoning is unavailable."}}
    if normalized in {"thanks", "thank you", "thanks jarvis"}:
        return {"spoken": "You’re welcome, " + name + ".", "card": {"kind": "conversation", "title": "You’re welcome", "items": [], "detail": "Local response."}}
    prior = next((turn["text"] for turn in reversed(history) if turn["role"] == "user"), None)
    if normalized in {"why", "why?", "what about the second one", "and that"} and prior:
        return {"spoken": "I can see we were discussing “" + prior[:120] + "”. The local fallback can’t reason through that follow-up yet. Try searching the indexed files or configure an approved model provider later.",
                "card": {"kind": "status", "title": "Model unavailable — local fallback", "items": [],
                         "detail": "The last topic is retained for this session, but open-ended reasoning is unavailable."}}
    return {"spoken": "I can search your indexed files, make a short study plan, or give a basic briefing. Open-ended reasoning is unavailable in local fallback.",
            "card": {"kind": "status", "title": "Model unavailable — local fallback", "items": [],
                     "detail": "No model provider is configured. The reply was not model-generated."}}
