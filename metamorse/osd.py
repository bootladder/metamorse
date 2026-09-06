"""The popup. Runs as its own process so tkinter's mainloop never blocks the
event loop; talks over stdin so the daemon can update or dismiss it.

Protocol, one JSON object per line:
    {"rows": [[letter, code, label, is_branch], ...], "path": "m", "keyed": ".-"}
    {"hide": true}     withdraw, stay resident
    {"close": true}    exit
"""
from __future__ import annotations

import json
import sys

MONO = "monospace"
BG, FG = "#16161c", "#e8e8ea"
DIM, ACCENT, LIVE, FADE = "#6a6a78", "#8fd0ff", "#ffd479", "#3a3a46"
WARN = "#ff8f8f"


def _match(code: str, keyed: str) -> str:
    """How a row relates to what has been keyed so far."""
    if not keyed:
        return "idle"
    if code == keyed:
        return "exact"
    return "live" if code.startswith(keyed) else "dead"


def _row_colors(state: str, is_branch: bool) -> tuple[str, str]:
    """(code colour, label colour) for a row in the given match state."""
    if state == "dead":
        return FADE, FADE
    if state in ("live", "exact"):
        return LIVE, FG
    return ACCENT, (DIM if is_branch else FG)


def _status(keyed: str, stray: str) -> tuple[str, str]:
    """(text, colour) for the header's right side."""
    if stray:
        return f"'{stray}' not here", WARN
    return (keyed, LIVE) if keyed else ("key a letter", DIM)


FOOTER = "hold = dash · tap = dot · single tap (e) dismisses"
POOL = 24               # rows built up front; more than any sane menu holds


class View:
    """A fixed pool of widgets, built once. Redrawing sets text and colour on
    existing labels -- destroying and reconstructing ~40 widgets per keystroke
    was the dominant cost in showing a menu."""

    def __init__(self, frame, tk):
        self.tk = tk
        self.where = tk.Label(frame, font=(MONO, 13, "bold"), bg=BG, fg=ACCENT,
                              anchor="w")
        self.where.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.status = tk.Label(frame, font=(MONO, 13, "bold"), bg=BG, fg=DIM,
                               anchor="e")
        self.status.grid(row=0, column=2, sticky="e", pady=(0, 8))

        self.rows = [self._row(frame, n) for n in range(1, POOL + 1)]

        self.footer = tk.Label(frame, text=FOOTER, font=(MONO, 10), bg=BG,
                               fg=DIM, anchor="w")
        self.footer.grid(row=POOL + 1, column=0, columnspan=3, sticky="w",
                         pady=(9, 0))

    def _row(self, frame, n):
        marker = self.tk.Label(frame, font=(MONO, 12), bg=BG, fg=LIVE)
        code = self.tk.Label(frame, font=(MONO, 12, "bold"), bg=BG, anchor="w")
        label = self.tk.Label(frame, font=(MONO, 12), bg=BG, anchor="w")
        marker.grid(row=n, column=0, sticky="w")
        code.grid(row=n, column=1, sticky="w", padx=(2, 10))
        label.grid(row=n, column=2, sticky="w")
        return marker, code, label

    def draw(self, rows, path, keyed, stray) -> None:
        self.where.config(text=f"metamorse · {' '.join(path.split()) or 'root'}")
        text, colour = _status(keyed, stray)
        self.status.config(text=text, fg=colour)

        for (marker, code_w, label_w), row in zip(self.rows, rows):
            letter, code, label, is_branch = row
            state = _match(code, keyed)
            code_fg, label_fg = _row_colors(state, is_branch)
            marker.config(text="▸" if state == "exact" else " ")
            code_w.config(text=f"{code:<6}{letter}", fg=code_fg)
            label_w.config(text=f"{'›' if is_branch else ' '} {label}", fg=label_fg)
            for widget in (marker, code_w, label_w):
                widget.grid()

        for marker, code_w, label_w in self.rows[len(rows):]:
            for widget in (marker, code_w, label_w):
                widget.grid_remove()


def _reader(queue):
    """stdin on its own thread; a blocking read must never stall the UI.

    readline() rather than `for line in sys.stdin`: iteration reads ahead into
    a buffer and can withhold a complete line until more arrives, which on a
    one-message-per-keystroke pipe means the message sits there unread.
    """
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        queue.put(line)
    queue.put(None)


def main() -> int:
    import queue as queuelib
    import threading
    import tkinter as tk

    inbox = queuelib.Queue()
    threading.Thread(target=_reader, args=(inbox,), daemon=True).start()

    root = tk.Tk()
    root.title("metamorse")
    root.configure(bg=BG)
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    frame = tk.Frame(root, bg=BG, padx=16, pady=13,
                     highlightthickness=1, highlightbackground="#2e2e3a")
    frame.pack()
    view = View(frame, tk)

    # Stay mapped, parked off-screen. withdraw()/deiconify() unmaps the window,
    # so the server drops it and the WM re-maps from nothing on every show;
    # moving an already-rendered window is one request.
    OFFSCREEN = 32000
    root.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")
    shown = {"at": None}

    def place() -> None:
        """Centre the window, recomputing its size only when the row count
        changed. A layout pass per keystroke is this process's biggest cost."""
        root.update_idletasks()
        size = (root.winfo_width(), root.winfo_height())
        x = (root.winfo_screenwidth() - size[0]) // 2
        y = int(root.winfo_screenheight() * 0.70) - size[1] // 2
        if shown["at"] != (x, y):
            shown["at"] = (x, y)
            root.geometry(f"+{x}+{y}")

    def hide() -> None:
        if shown["at"] is not None:
            shown["at"] = None
            root.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")

    def poll() -> None:
        try:
            while True:                          # drain: only the last matters
                line = inbox.get_nowait()
                if line is None:
                    return root.destroy()
                message = json.loads(line)
                if message.get("close"):
                    return root.destroy()
                if message.get("hide"):
                    hide()
                    continue
                view.draw(message["rows"], message.get("path", ""),
                          message.get("keyed", ""), message.get("stray", ""))
                place()
        except queuelib.Empty:
            pass
        root.after(4, poll)

    root.after(4, poll)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
