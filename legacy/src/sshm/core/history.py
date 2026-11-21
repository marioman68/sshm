"""Persistent availability history and event log (SQLite, ~/.local/state/sshm/history.db).

Only the sshm process that owns the telemetry listener (normally the tray)
*writes*; every front-end can read. Samples are stored at most once a minute
per server (or immediately when the up/down state changes) and pruned after
30 days, so the database stays small.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from sshm.core import paths

SAMPLE_EVERY = 60          # seconds between stored samples while the state is unchanged
KEEP_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    server_id TEXT NOT NULL,
    ts        INTEGER NOT NULL,
    online    INTEGER NOT NULL,
    latency   REAL,
    cpu       REAL,
    mem       REAL,
    disk      REAL
);
CREATE INDEX IF NOT EXISTS samples_by_server ON samples(server_id, ts);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    server_id   TEXT NOT NULL,
    server_name TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_by_ts ON events(ts);
CREATE TABLE IF NOT EXISTS active (
    server_id TEXT NOT NULL,
    kind      TEXT NOT NULL,
    since     INTEGER NOT NULL,
    severity  TEXT NOT NULL,
    message   TEXT NOT NULL,
    PRIMARY KEY (server_id, kind)
);
"""


@dataclass
class Event:
    ts: float
    server_id: str
    server_name: str
    kind: str          # offline | cpu | mem | disk | container | unhealthy | reboot
    severity: str      # critical | warning | info
    message: str
    resolved: bool = False
    id: int = 0

    @property
    def time_label(self) -> str:
        age = time.time() - self.ts
        if age < 86400:
            return time.strftime("%H:%M", time.localtime(self.ts))
        return time.strftime("%b %d %H:%M", time.localtime(self.ts))


@dataclass
class Availability:
    uptime_24h: float | None
    uptime_7d: float | None
    latency: list[float]          # average latency per bucket (ms), oldest first; 0 = offline/no data

    @staticmethod
    def label(pct: float | None) -> str:
        if pct is None:
            return "--"
        return "100%" if pct >= 99.995 else f"{pct:.2f}%" if pct >= 99 else f"{pct:.1f}%"


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.history_file()
        paths.ensure_dir(self.path.parent)
        self._local = threading.local()
        self._last: dict[str, tuple[float, int]] = {}
        with self._conn() as db:
            db.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------- writing
    def record(self, server_id: str, online: bool, latency: float | None = None, cpu: float | None = None,
               mem: float | None = None, disk: float | None = None, now: float | None = None) -> bool:
        """Store a sample if a minute passed or the up/down state changed. Returns True if stored."""
        now = now or time.time()
        last = self._last.get(server_id)
        if last and now - last[0] < SAMPLE_EVERY and last[1] == int(online):
            return False
        self._last[server_id] = (now, int(online))
        self._conn().execute(
            "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?)",
            (server_id, int(now), int(online), latency, cpu, mem, disk),
        )
        return True

    def add_event(self, ev: Event) -> Event:
        cur = self._conn().execute(
            "INSERT INTO events (ts, server_id, server_name, kind, severity, message, resolved) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(ev.ts), ev.server_id, ev.server_name, ev.kind, ev.severity, ev.message, int(ev.resolved)),
        )
        ev.id = cur.lastrowid or 0
        db = self._conn()
        if ev.resolved:
            db.execute("DELETE FROM active WHERE server_id=? AND kind=?", (ev.server_id, ev.kind))
        else:
            db.execute("INSERT OR REPLACE INTO active VALUES (?, ?, ?, ?, ?)",
                       (ev.server_id, ev.kind, int(ev.ts), ev.severity, ev.message))
        return ev

    def clear_active(self) -> None:
        self._conn().execute("DELETE FROM active")

    def clear_events(self) -> None:
        self._conn().execute("DELETE FROM events")

    def prune(self, days: int = KEEP_DAYS) -> None:
        cutoff = int(time.time() - days * 86400)
        db = self._conn()
        db.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))

    def forget(self, server_id: str) -> None:
        db = self._conn()
        for table in ("samples", "events", "active"):
            db.execute(f"DELETE FROM {table} WHERE server_id=?", (server_id,))

    # ------------------------------------------------------------- reading
    def uptime(self, server_id: str, seconds: float, now: float | None = None) -> float | None:
        """Percentage of time online over the window, weighting each sample by how long it held."""
        now = now or time.time()
        start = now - seconds
        rows = self._conn().execute(
            "SELECT ts, online FROM samples WHERE server_id=? AND ts>=? ORDER BY ts",
            (server_id, int(start)),
        ).fetchall()
        prev = self._conn().execute(
            "SELECT ts, online FROM samples WHERE server_id=? AND ts<? ORDER BY ts DESC LIMIT 1",
            (server_id, int(start)),
        ).fetchone()
        if not rows and not prev:
            return None
        points = ([(start, prev[1])] if prev else []) + [(float(t), o) for t, o in rows]
        up = total = 0.0
        for (t, online), nxt in zip(points, [*points[1:], (now, None)], strict=True):
            span = max(0.0, min(nxt[0], now) - t)
            if span > 3 * SAMPLE_EVERY:   # a long gap means nobody was watching: don't extrapolate
                span = SAMPLE_EVERY
            total += span
            up += span if online else 0.0
        return 100.0 * up / total if total else None

    def latency_series(self, server_id: str, seconds: float = 86400, buckets: int = 48,
                       now: float | None = None) -> list[float]:
        now = now or time.time()
        start = now - seconds
        width = seconds / buckets
        sums = [0.0] * buckets
        counts = [0] * buckets
        for ts, online, latency in self._conn().execute(
            "SELECT ts, online, latency FROM samples WHERE server_id=? AND ts>=?", (server_id, int(start))
        ):
            if online and latency is not None:
                i = min(buckets - 1, int((ts - start) / width))
                sums[i] += latency
                counts[i] += 1
        return [sums[i] / counts[i] if counts[i] else 0.0 for i in range(buckets)]

    def availability(self, server_id: str) -> Availability:
        return Availability(self.uptime(server_id, 86400), self.uptime(server_id, 7 * 86400),
                            self.latency_series(server_id))

    def events(self, limit: int = 200, server_id: str | None = None) -> list[Event]:
        q = "SELECT id, ts, server_id, server_name, kind, severity, message, resolved FROM events"
        args: tuple = ()
        if server_id:
            q += " WHERE server_id=?"
            args = (server_id,)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"
        return [Event(ts, sid, name, kind, sev, msg, bool(res), id=eid)
                for eid, ts, sid, name, kind, sev, msg, res in self._conn().execute(q, (*args, limit))]

    def active(self) -> list[Event]:
        return [Event(since, sid, "", kind, sev, msg)
                for sid, kind, since, sev, msg in self._conn().execute(
                    "SELECT server_id, kind, since, severity, message FROM active ORDER BY since DESC")]
