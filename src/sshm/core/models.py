"""Data model for server profiles."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_mac(value: str) -> str:
    """Return ``aa:bb:cc:dd:ee:ff`` or ``""``. Raises ``ValueError`` on garbage."""
    raw = re.sub(r"[\s:.\-]", "", (value or "").lower())
    if not raw:
        return ""
    if not _MAC_RE.match(raw):
        raise ValueError(f"'{value}' is not a valid MAC address")
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


@dataclass
class CustomCommand:
    label: str
    command: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "command": self.command}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomCommand:
        return cls(
            label=str(data.get("label", "")).strip(),
            command=str(data.get("command") or data.get("cmd") or "").strip(),
        )


@dataclass
class Server:
    name: str
    host: str
    user: str = ""
    port: int = 22
    tag: str = ""
    mac: str = ""
    key: str = ""
    jump: str = ""
    remote_path: str = ""
    tmux: bool = False
    tray: bool = True
    favorite: bool = False
    notes: str = ""
    commands: list[CustomCommand] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    last_connected: float = 0.0

    # ------------------------------------------------------------------ derived
    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def endpoint(self) -> str:
        return f"{self.target}:{self.port}"

    @property
    def key_path(self) -> str:
        """Expanded identity file path, or ``""`` if unset or missing."""
        if not self.key:
            return ""
        path = os.path.expanduser(os.path.expandvars(self.key))
        return path if os.path.isfile(path) else ""

    @property
    def home_path(self) -> str:
        if self.remote_path:
            return self.remote_path if self.remote_path.startswith("/") else f"/{self.remote_path}"
        if self.user == "root":
            return "/root"
        return f"/home/{self.user}" if self.user else "/"

    @property
    def sftp_url(self) -> str:
        return f"{self.sftp_url_prefix}{self.home_path.lstrip('/')}"

    @property
    def sftp_url_prefix(self) -> str:
        who = f"{self.user}@" if self.user else ""
        return f"sftp://{who}{self.host}:{self.port}/"

    # --------------------------------------------------------------- behaviour
    def matches(self, query: str) -> bool:
        return fuzzy_score(query, self.search_text) > 0

    @property
    def search_text(self) -> str:
        return " ".join(filter(None, [self.name, self.host, self.user, self.tag, self.notes]))

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("Name is required")
        if not self.host.strip():
            errors.append("Host is required")
        if any(c.isspace() for c in self.host.strip()):
            errors.append("Host must not contain spaces")
        if not 1 <= int(self.port) <= 65535:
            errors.append("Port must be between 1 and 65535")
        try:
            normalize_mac(self.mac)
        except ValueError as exc:
            errors.append(str(exc))
        for value in (self.name, self.host, self.user, self.tag, self.key, self.jump):
            if "\n" in value or "\r" in value:
                errors.append("Fields must not contain line breaks")
                break
        return errors

    # ----------------------------------------------------------- serialisation
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["commands"] = [c.to_dict() for c in self.commands]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Server:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["name"] = str(kwargs.get("name", "")).strip()
        kwargs["host"] = str(kwargs.get("host", "")).strip()
        for key in ("user", "tag", "key", "jump", "remote_path", "notes"):
            kwargs[key] = str(kwargs.get(key) or "").strip()
        try:
            kwargs["port"] = int(kwargs.get("port") or 22)
        except (TypeError, ValueError):
            kwargs["port"] = 22
        try:
            kwargs["mac"] = normalize_mac(str(kwargs.get("mac") or ""))
        except ValueError:
            kwargs["mac"] = ""
        for key in ("tmux", "tray", "favorite"):
            if key in kwargs:
                kwargs[key] = bool(kwargs[key])
        kwargs["commands"] = [
            CustomCommand.from_dict(c) for c in data.get("commands", []) if isinstance(c, dict)
        ]
        kwargs["commands"] = [c for c in kwargs["commands"] if c.label and c.command]
        kwargs["id"] = str(kwargs.get("id") or new_id())
        kwargs["last_connected"] = float(kwargs.get("last_connected") or 0.0)
        return cls(**kwargs)


def fuzzy_score(query: str, text: str) -> int:
    """Rank *text* against *query*; 0 means no match.

    Substring hits score highest (earlier is better). Otherwise every query
    character must start a word in *text* in order ("hl" matches "home-lab").
    """
    query = query.strip().lower()
    if not query:
        return 1
    text = text.lower()
    pos = text.find(query)
    if pos >= 0:
        return 1000 - pos
    starts = [i for i, ch in enumerate(text) if ch.isalnum() and (i == 0 or not text[i - 1].isalnum())]
    ti = 0
    for ch in query:
        while ti < len(starts) and text[starts[ti]] != ch:
            ti += 1
        if ti == len(starts):
            return 0
        ti += 1
    return 100
