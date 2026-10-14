"""
Prompt-safety filters. Three checkpoints:

1. INPUT  (check_query)      - before we embed the user's question
     * length / empty checks
     * prompt-injection phrases ("ignore previous instructions", "show system prompt"...)
     * PII redaction (email, phone, Aadhaar, PAN, card numbers) so personal data is
       not sent to the embedding provider or written to logs
     * requests for credentials ("what is the admin password")
2. EVIDENCE (scan_text)      - on every chunk at ingestion time and again at query time
     * chunks that contain injection-style instructions are flagged and never
       returned as evidence (defends against a poisoned document)
3. OUTPUT (redact_secrets)   - before evidence leaves the API
     * masks things that look like API keys, passwords, tokens

Honest limitation (say this in interviews): pattern matching is a *secondary*
signal. The real protections are server-side access filters, treating documents
as data (never instructions), fixed allowlisted actions, and user confirmation.
"""
import re
from dataclasses import dataclass, field

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
    r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|your)\s+(instructions|rules)",
    r"forget\s+(all\s+)?(your|the|previous)\s+(instructions|rules)",
    r"(reveal|show|print|repeat|leak)\s+(me\s+)?(your|the)\s+(system|hidden|developer)\s+(prompt|instructions|message)",
    r"\byou\s+are\s+now\s+(a|an|in)\b",
    r"\b(developer|dan|god)\s+mode\b",
    r"\bjailbreak\b",
    r"\bact\s+as\s+(an?\s+)?(admin|administrator|root|system)\b",
    r"(run|execute|call|trigger)\s+(the\s+)?(tool|action|flow|function)\s+",
    r"\boverride\s+(the\s+)?(safety|security|policy|rules)\b",
    r"<\s*/?\s*(system|assistant)\s*>",
]
CREDENTIAL_PATTERNS = [
    # Asking for a credential *value* ("what is the admin password") - but not
    # process questions ("what is the password reset process").
    r"\b(what\s+is|what's|tell\s+me|give\s+me|share|send\s+me)\s+(the\s+|your\s+|an?\s+)?(\w+\s+){0,2}"
    r"(password|passcode|api\s*key|secret\s*key|access\s*token|credentials?)\b"
    r"(?!\s+(reset|policy|process|change|expiry|rules?|requirements?|complexity))",
]

PII_PATTERNS = {
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "AADHAAR": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    "CARD": r"\b(?:\d[ -]?){13,16}\b",
    "PAN": r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "PHONE": r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)",
}

SECRET_PATTERNS = [
    r"\b(sk|pk|rk)[-_][A-Za-z0-9_-]{16,}\b",  # generic secret-key style
    r"\bpcsk_[A-Za-z0-9_]{20,}\b",  # Pinecone key style
    r"\bAKIA[0-9A-Z]{16}\b",  # AWS access key id
    r"(?i)\b(password|passwd|pwd|secret|api[_ ]?key|token)\s*[:=]\s*\S+",
]

_inj = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_cred = [re.compile(p, re.IGNORECASE) for p in CREDENTIAL_PATTERNS]
_pii = {k: re.compile(p) for k, p in PII_PATTERNS.items()}
_sec = [re.compile(p) for p in SECRET_PATTERNS]


@dataclass
class QueryCheck:
    allowed: bool
    clean_query: str
    reason: str = ""  # machine-readable: EMPTY, TOO_LONG, PROMPT_INJECTION, CREDENTIAL_REQUEST
    pii_found: list = field(default_factory=list)


def find_injection(text: str) -> list:
    return [p.pattern for p in _inj if p.search(text)]


def redact_pii(text: str):
    found = []
    for label, pattern in _pii.items():
        if pattern.search(text):
            found.append(label)
            text = pattern.sub(f"[{label}]", text)
    return text, found


def check_query(query: str, max_chars: int = 500) -> QueryCheck:
    q = (query or "").strip()
    if not q:
        return QueryCheck(False, "", "EMPTY")
    if len(q) > max_chars:
        return QueryCheck(False, "", "TOO_LONG")
    if find_injection(q):
        return QueryCheck(False, "", "PROMPT_INJECTION")
    if any(p.search(q) for p in _cred):
        return QueryCheck(False, "", "CREDENTIAL_REQUEST")
    clean, pii = redact_pii(q)
    return QueryCheck(True, clean, "", pii)


def scan_text(text: str) -> bool:
    """True if a document chunk looks like it is trying to instruct the AI."""
    return bool(find_injection(text))


def redact_secrets(text: str) -> str:
    for p in _sec:
        text = p.sub("[REDACTED]", text)
    return text
