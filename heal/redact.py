"""Logs go to the model, so secrets come out first and only the tail (where errors are) goes in."""
from __future__ import annotations

import re

PATTERNS = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)(\s*[=:]\s*)\S+"), r"\1\2[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED_JWT]"),
]


def redact(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text


def tail(text: str, chars: int = 8000) -> str:
    text = redact(text)
    if len(text) <= chars:
        return text
    return f"[... {len(text) - chars} earlier characters omitted; showing the end of the log ...]\n" + text[-chars:]
