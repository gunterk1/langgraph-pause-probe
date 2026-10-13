"""The world the routers ask about -- a SQLite database outside the graph.

This is the whole point of the probe. In discogs-filler the router asks
"is this record already listed?", and that is a question about the world, not
about the graph. The world changes between the question and the answer; the
original ADK run died on exactly that with `Replay divergence detected`.

Everything here is deliberately trivial. The experiment is not about the
domain, it is about what the framework does when a paused branch resumes into
a world that moved.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

OPEN = "OPEN"
GRADED = "GRADED"
LISTED = "LISTED"


class World:
    """One SQLite connection PER THREAD.

    Found the hard way: LangGraph runs fanned-out branches in a real thread
    pool, and a single shared connection fails there with
    `sqlite3.InterfaceError: bad parameter or other API misuse` -- sometimes.
    It is a race, so it passed the first smoke run and blew up on the second.
    That is a fact about the framework worth writing down: the branches are
    not cooperatively scheduled, they are threads.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (item_id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls   (node TEXT NOT NULL, item_id TEXT NOT NULL);
            """
        )
        self.db.commit()

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    # -- state ------------------------------------------------------------
    def seed(self, item_ids: list[str]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO records VALUES (?, ?)", [(i, OPEN) for i in item_ids]
        )
        self.db.commit()

    def state_of(self, item_id: str) -> str:
        row = self.db.execute(
            "SELECT state FROM records WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row[0] if row else OPEN

    def mark_graded(self, item_id: str) -> None:
        """Already has a condition grade -- needs no human, only a listing."""
        self.db.execute("UPDATE records SET state = ? WHERE item_id = ?", (GRADED, item_id))
        self.db.commit()

    def mark_listed(self, item_id: str) -> None:
        """Move the world. Called by the graph -- and by the experiment."""
        self.db.execute("UPDATE records SET state = ? WHERE item_id = ?", (LISTED, item_id))
        self.db.commit()

    def listed(self) -> list[str]:
        return [
            r[0]
            for r in self.db.execute(
                "SELECT item_id FROM records WHERE state = ? ORDER BY item_id", (LISTED,)
            )
        ]

    # -- instrumentation --------------------------------------------------
    def record_call(self, node: str, item_id: str) -> None:
        """Every node execution is logged to the database, not to memory.

        A counter in memory would be reset by the resume and would answer the
        wrong question. What is being measured is how often a node *actually
        ran* across a pause, and only the database survives that.
        """
        self.db.execute("INSERT INTO calls VALUES (?, ?)", (node, item_id))
        self.db.commit()

    def calls(self, node: str, item_id: str | None = None) -> int:
        if item_id is None:
            row = self.db.execute("SELECT count(*) FROM calls WHERE node = ?", (node,)).fetchone()
        else:
            row = self.db.execute(
                "SELECT count(*) FROM calls WHERE node = ? AND item_id = ?", (node, item_id)
            ).fetchone()
        return row[0]
