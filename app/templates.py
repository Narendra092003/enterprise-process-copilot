"""
Context-aware response templates.

The retrieval API is not a free-form chatbot. It (1) detects what *kind* of
question this is, then (2) fills a fixed template with retrieved evidence, so
every answer has the same safe shape: answer + source + next step.

Intents (simple keyword rules - explainable and easy to test):
    how_to        "How do I request VPN access?"      -> numbered steps + source
    policy        "How many casual leaves do I get?"  -> quoted rule + source
    troubleshoot  "Outlook is not syncing"            -> fixes + escalation route
    contact       "Who approves travel expenses?"     -> owner / contact + source
    general       anything else                       -> best passage + source

Fallback templates handle: no evidence, low confidence, blocked input.

In Copilot Studio you can either show `answer_text` directly (Option A) or let
Copilot write the answer from the evidence (Option B, custom knowledge topic).
"""
import re

INTENT_RULES = [
    ("troubleshoot", r"\b(not \w+ing|not working|error|issue|problem|fail(ed|ing|s)?|unable|can't|cannot|broken|fix|stuck|locked out|slow|crash\w*)\b"),
    ("contact", r"\b(who|contact|email|phone|reach|escalat\w*|owner|approver|approves?)\b"),
    ("how_to", r"\b(how (do|can|should) i|how to|steps?|process|procedure|apply|request|submit|raise|set ?up|register|onboard\w*)\b"),
    ("policy", r"\b(policy|allowed|eligib\w*|entitle\w*|limit|maximum|minimum|how (many|much)|can i|am i|rules?|rate|reimburs\w*)\b"),
]

STEP_LINE = re.compile(r"^\s*(\d+[.)]|[-*•])\s+")

BLOCK_MESSAGES = {
    "PROMPT_INJECTION": "I can only answer questions about our internal processes and policies, "
    "and I can't change how I work or reveal my instructions.",
    "CREDENTIAL_REQUEST": "I can't share passwords, keys or other credentials. "
    "If you need access, I can explain the access request process instead.",
    "TOO_LONG": "That question is too long for me. Please ask it in one or two sentences.",
    "EMPTY": "Please type a question about a process or policy.",
    "RATE_LIMITED": "You're sending questions very quickly. Please wait a moment and try again.",
}


def detect_intent(query: str) -> str:
    q = query.lower()
    for intent, pattern in INTENT_RULES:
        if re.search(pattern, q):
            return intent
    return "general"


def _citation(ev: dict) -> str:
    where = []
    if ev.get("section"):
        where.append(ev["section"])
    if ev.get("page") and ev["page"] > 1:
        where.append(f"page {ev['page']}")
    suffix = f" — {', '.join(where)}" if where else ""
    link = ev.get("content_location") or ""
    return f"[{ev['title']}{suffix}]({link})" if link else f"{ev['title']}{suffix}"


def _steps_or_excerpt(text: str, max_lines: int = 8) -> str:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    steps = [l for l in lines if STEP_LINE.match(l)]
    if len(steps) >= 2:
        return "\n".join(steps[:max_lines])
    excerpt = " ".join(lines)
    return excerpt if len(excerpt) <= 600 else excerpt[:600].rsplit(" ", 1)[0] + " …"


INTENT_HINTS = {
    "how_to": STEP_LINE,
    "troubleshoot": STEP_LINE,
    "contact": re.compile(r"(approv|contact|@|helpdesk|service desk|extension|handles)", re.IGNORECASE),
}


def pick_best(intent: str, evidence: list) -> dict:
    """Context-aware choice of the passage to show.

    Retrieval ranks by similarity only. For a "how to" question a passage with
    numbered steps is more useful than an introduction from the same document,
    so among the top passages of the best document we prefer one that fits the
    question type."""
    top_doc = evidence[0]["document_id"]
    hint = INTENT_HINTS.get(intent)
    if hint:
        for ev in evidence[:4]:
            if ev["document_id"] != top_doc:
                continue
            text = ev["content"]
            matches = hint.findall(text) if hint is not STEP_LINE else [l for l in text.splitlines() if STEP_LINE.match(l)]
            if (hint is STEP_LINE and len(matches) >= 2) or (hint is not STEP_LINE and matches):
                return ev
    return evidence[0]


def render_answer(intent: str, evidence: list, support_route: str) -> str:
    top = pick_best(intent, evidence)
    body = _steps_or_excerpt(top["content"])
    src = _citation(top)

    if intent == "how_to":
        text = f"Here's the process from **{top['title']}**:\n\n{body}\n\nSource: {src}"
    elif intent == "policy":
        text = f"According to **{top['title']}**:\n\n> {body}\n\nSource: {src}"
    elif intent == "troubleshoot":
        text = (
            f"Try these steps from **{top['title']}**:\n\n{body}\n\n"
            f"If that doesn't fix it, contact {support_route}.\n\nSource: {src}"
        )
    elif intent == "contact":
        text = f"From **{top['title']}**:\n\n{body}\n\nSource: {src}"
    else:
        text = f"Here's what I found in **{top['title']}**:\n\n{body}\n\nSource: {src}"

    others = [e for e in evidence[:3] if e["title"] != top["title"]]
    if others:
        text += "\n\nRelated: " + "; ".join(_citation(e) for e in others)
    return text


def render_no_evidence(reason: str, support_route: str) -> str:
    if reason == "LOW_CONFIDENCE":
        return (
            "I found some documents, but none of them clearly answers this, so I won't guess. "
            f"Try rephrasing, or contact {support_route}."
        )
    return (
        "I couldn't find this in the approved documents I have access to. "
        f"Please contact {support_route}."
    )


def render_blocked(reason: str) -> str:
    return BLOCK_MESSAGES.get(reason, "I can't help with that request.")


def action_prompt(action: str) -> str:
    labels = {
        "CreateAccessRequest": "Would you like me to raise an access request for you? "
        "I'll show you the details and ask you to confirm first.",
    }
    return labels.get(action, "")
