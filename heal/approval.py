"""Human approval for medium-risk actions. Default answer is NO.

AUTO_APPROVE=yes|no answers unattended runs. With no terminal and no setting, it is no.
To plug in Slack/Teams/PagerDuty, replace ask() with a call that posts the request and
waits for a button press; nothing else changes."""
from __future__ import annotations

import os
import sys


def ask(summary: str) -> bool:
    print(f"\n    >>> APPROVAL NEEDED: {summary}")
    auto = os.getenv("AUTO_APPROVE", "").strip().lower()
    if auto in ("yes", "no"):
        print(f"    >>> (AUTO_APPROVE={auto})")
        return auto == "yes"
    if not sys.stdin.isatty():
        print("    >>> no one at the keyboard -> denied")
        return False
    return input("    >>> approve? [y/N] ").strip().lower() == "y"
