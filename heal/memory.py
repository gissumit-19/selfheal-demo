"""Durable agent memory (SQLite) + an append-only audit log (JSONL).

  history     signature -> action -> outcome, across incidents: "what fixed this before?"
  attempts    actions executed per incident: the guard's attempt limit reads this
  processed   incidents already handled, so a poller never handles one twice
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _words(s: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", s.lower()) if len(w) > 3}


class Memory:
    def __init__(self, runtime_dir: Path):
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = runtime_dir / "audit.jsonl"
        self.db = sqlite3.connect(runtime_dir / "heal.db")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS history (signature TEXT, source TEXT, action TEXT, outcome TEXT, incident TEXT, ts TEXT);
            CREATE TABLE IF NOT EXISTS attempts (incident TEXT, action TEXT, result TEXT, ts TEXT);
            CREATE TABLE IF NOT EXISTS processed (incident TEXT PRIMARY KEY, outcome TEXT, ts TEXT);
        """)

    # -------- history --------
    def similar(self, signature: str, limit: int = 10) -> list[dict]:
        want = _words(signature)
        rows = self.db.execute("SELECT signature, source, action, outcome, incident, ts FROM history ORDER BY ts DESC").fetchall()
        hits = [r for r in rows if len(want & _words(r[0])) >= max(1, min(2, len(want)))]
        return [dict(zip(("signature", "source", "action", "outcome", "incident", "ts"), r)) for r in hits[:limit]]

    def resolved_count(self, signature: str, action: str) -> int:
        return sum(1 for h in self.similar(signature, 100) if h["action"] == action and h["outcome"] == "resolved")

    def add_history(self, signature: str, source: str, action: str, outcome: str, incident: str) -> None:
        self.db.execute("INSERT INTO history VALUES (?,?,?,?,?,?)", (signature, source, action, outcome, incident, now()))
        self.db.commit()

    # -------- attempts --------
    def attempts(self, incident: str, action: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM attempts WHERE incident=? AND action=?", (incident, action)).fetchone()[0]

    def record_attempt(self, incident: str, action: str, result: str) -> None:
        self.db.execute("INSERT INTO attempts VALUES (?,?,?,?)", (incident, action, result, now()))
        self.db.commit()

    # -------- processed --------
    def is_processed(self, incident: str) -> bool:
        return self.db.execute("SELECT 1 FROM processed WHERE incident=?", (incident,)).fetchone() is not None

    def mark_processed(self, incident: str, outcome: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO processed VALUES (?,?,?)", (incident, outcome, now()))
        self.db.commit()

    # -------- audit --------
    def audit(self, incident: str, step: str, **detail) -> None:
        with self.audit_path.open("a") as f:
            f.write(json.dumps({"ts": now(), "incident": incident, "step": step, **detail}, default=str) + "\n")
