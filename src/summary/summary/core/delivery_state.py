"""Durable email checkpoints; never blindly retry an ambiguous SMTP outcome."""

import sqlite3
from pathlib import Path


class DeliveryUncertain(Exception):
    """SMTP may already have accepted the message; operator review is required."""


class DeliveryState:
    """Keep delivery bookkeeping separate from personal memory."""

    def __init__(self, memory_file):
        """Create the additive delivery ledger beside the existing memory file."""
        self.path = Path(memory_file).parent / "delivery.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS deliveries "
                "(key TEXT PRIMARY KEY, summary TEXT, "
                "status TEXT NOT NULL DEFAULT 'ready')"
            )
        self.path.chmod(0o600)

    def db(self):
        """Open a short-lived transactional connection."""
        return sqlite3.connect(self.path, timeout=30)

    def summary(self, key):
        """Read the exact document chosen for a delivery stage."""
        with self.db() as db:
            row = db.execute(
                "SELECT summary FROM deliveries WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else None

    def remember(self, key, summary):
        """Keep the first selected document across task retries."""
        with self.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO deliveries(key,summary) VALUES (?,?)",
                (key, summary),
            )
        return self.summary(key)

    def status(self, key):
        """Read the transport checkpoint without changing it."""
        with self.db() as db:
            row = db.execute(
                "SELECT status FROM deliveries WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else "ready"

    def claim(self, key):
        """Atomically reserve one send; never reclaim an uncertain attempt."""
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO deliveries(key) VALUES (?)", (key,))
            changed = db.execute(
                "UPDATE deliveries SET status='sending' WHERE key=? AND status='ready'",
                (key,),
            ).rowcount
        if changed:
            return True
        if self.status(key) == "sent":
            return False
        raise DeliveryUncertain(
            "Email transmission outcome requires review; not resending"
        )

    def finish(self, key, status):
        """Record SMTP acceptance or an ambiguous transport failure."""
        with self.db() as db:
            db.execute("UPDATE deliveries SET status=? WHERE key=?", (status, key))
