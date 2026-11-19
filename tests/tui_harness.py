"""Run the TUI in a pseudo-terminal and reconstruct the screen.

A deliberately small VT/xterm emulator: enough of CSI cursor movement, erase,
repeat and scroll handling to rebuild what ncurses draws, so tests (and humans)
can assert on the rendered text.
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time

CSI = re.compile(rb"\x1b\[([?>=]?)([0-9;]*)([@A-Za-z`])")


class Screen:
    def __init__(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        self.grid = [[" "] * cols for _ in range(rows)]
        self.y = self.x = 0
        self.top, self.bottom = 0, rows - 1
        self.last = " "
        self._pending = b""

    def _put(self, ch: str) -> None:
        if self.x >= self.cols:
            self.x = 0
            self._lf()
        self.grid[self.y][self.x] = ch
        self.last = ch
        self.x += 1

    def _lf(self) -> None:
        if self.y == self.bottom:
            del self.grid[self.top]
            self.grid.insert(self.bottom, [" "] * self.cols)
        else:
            self.y = min(self.rows - 1, self.y + 1)

    def feed(self, data: bytes) -> None:
        data = self._pending + data
        self._pending = b""
        i = 0
        while i < len(data):
            b = data[i]
            if b == 0x1B:
                m = CSI.match(data, i)
                if m:
                    self._csi(m.group(1), m.group(2).decode(), m.group(3).decode())
                    i = m.end()
                    continue
                rest = data[i:]
                if rest == b"\x1b" or (rest.startswith(b"\x1b[") and len(rest) < 32
                                        and not re.search(rb"[@A-Za-z`]", rest[2:])):
                    self._pending = rest
                    return
                nxt = data[i + 1:i + 2]
                if nxt == b"]":  # OSC ... BEL/ST
                    end = data.find(b"\x07", i)
                    i = end + 1 if end >= 0 else len(data)
                    continue
                if nxt in (b"(", b")"):
                    i += 3
                    continue
                if nxt == b"M":  # reverse index
                    if self.y == self.top:
                        del self.grid[self.bottom]
                        self.grid.insert(self.top, [" "] * self.cols)
                    else:
                        self.y -= 1
                i += 2
                continue
            if b == 0x0D:
                self.x = 0
            elif b == 0x0A:
                self._lf()
            elif b == 0x08:
                self.x = max(0, self.x - 1)
            elif b in (0x07, 0x0F, 0x0E):
                pass
            elif b >= 0x20:
                # decode one UTF-8 character
                n = 1 if b < 0x80 else 2 if b < 0xE0 else 3 if b < 0xF0 else 4
                if i + n > len(data):
                    self._pending = data[i:]
                    return
                self._put(data[i:i + n].decode("utf-8", "replace"))
                i += n
                continue
            i += 1

    def _csi(self, priv: str, params: str, cmd: str) -> None:
        if priv:
            return
        nums = [int(p) if p else 0 for p in params.split(";")] if params else []

        def n(idx: int = 0, default: int = 1) -> int:
            return nums[idx] if len(nums) > idx and nums[idx] else default

        if cmd in "Hf":
            self.y = min(self.rows - 1, n(0) - 1)
            self.x = min(self.cols - 1, n(1) - 1)
        elif cmd == "A":
            self.y = max(0, self.y - n())
        elif cmd == "B":
            self.y = min(self.rows - 1, self.y + n())
        elif cmd == "C":
            self.x = min(self.cols - 1, self.x + n())
        elif cmd == "D":
            self.x = max(0, self.x - n())
        elif cmd == "G" or cmd == "`":
            self.x = min(self.cols - 1, n() - 1)
        elif cmd == "d":
            self.y = min(self.rows - 1, n() - 1)
        elif cmd == "K":
            mode = n(0, 0)
            row = self.grid[self.y]
            rng = range(self.x, self.cols) if mode == 0 else range(0, self.x + 1) if mode == 1 else range(self.cols)
            for c in rng:
                row[c] = " "
        elif cmd == "J":
            mode = n(0, 0)
            if mode == 2 or mode == 3:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
            elif mode == 0:
                for c in range(self.x, self.cols):
                    self.grid[self.y][c] = " "
                for r in range(self.y + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
        elif cmd == "X":
            for c in range(self.x, min(self.cols, self.x + n())):
                self.grid[self.y][c] = " "
        elif cmd == "b":
            for _ in range(n()):
                self._put(self.last)
        elif cmd == "r":
            self.top = n(0) - 1
            self.bottom = (nums[1] if len(nums) > 1 and nums[1] else self.rows) - 1
            self.y = self.x = 0
        elif cmd == "S":
            for _ in range(n()):
                del self.grid[self.top]
                self.grid.insert(self.bottom, [" "] * self.cols)
        elif cmd == "T":
            for _ in range(n()):
                del self.grid[self.bottom]
                self.grid.insert(self.top, [" "] * self.cols)
        elif cmd == "L":
            for _ in range(n()):
                del self.grid[self.bottom]
                self.grid.insert(self.y, [" "] * self.cols)
        elif cmd == "M":
            for _ in range(n()):
                del self.grid[self.y]
                self.grid.insert(self.bottom, [" "] * self.cols)
        elif cmd == "P":
            row = self.grid[self.y]
            for _ in range(n()):
                del row[self.x]
                row.append(" ")
        elif cmd == "@":
            row = self.grid[self.y]
            for _ in range(n()):
                row.insert(self.x, " ")
                row.pop()

    def text(self) -> str:
        return "\n".join("".join(r).rstrip() for r in self.grid)


class TUIProcess:
    def __init__(self, env: dict, rows: int = 40, cols: int = 132, argv: list[str] | None = None) -> None:
        self.screen = Screen(rows, cols)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.update(env)
            os.environ["TERM"] = "xterm-256color"
            os.environ["LANG"] = os.environ["LC_ALL"] = "C.UTF-8"
            argv = argv or [sys.executable, "-m", "sshm"]
            os.execvp(argv[0], argv)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(self, seconds: float = 0.6) -> str:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.screen.feed(data)
        return self.screen.text()

    def send(self, keys: str | bytes, wait: float = 0.5) -> str:
        os.write(self.fd, keys.encode() if isinstance(keys, str) else keys)
        return self.pump(wait)

    def close(self, timeout: float = 4.0) -> int:
        """Back out of any open dialog and quit; kill the child if it will not exit."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                return 0
            if pid:
                return os.waitstatus_to_exitcode(status)
            try:
                os.write(self.fd, b"\x1b")
                time.sleep(0.1)
                os.write(self.fd, b"q")
            except OSError:
                pass
            self.pump(0.3)
        os.kill(self.pid, 9)
        os.waitpid(self.pid, 0)
        return -9


if __name__ == "__main__":  # manual: python tests/tui_harness.py
    proc = TUIProcess(dict(os.environ))
    print(proc.pump(1.5))
    proc.close()
