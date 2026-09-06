"""The popup. Runs as its own process so tkinter's mainloop never blocks the
event loop; talks over stdin so the daemon can update or dismiss it.

Protocol, one JSON object per line:
    {"rows": [[letter, code, label, is_branch], ...], "path": "m", "keyed": ".-"}
    {"close": true}
"""
from __future__ import annotations

import json
import sys

MONO = "monospace"
BG, FG = "#16161c", "#e8e8ea"
DIM, ACCENT, LIVE, FADE = "#6a6a78", "#8fd0ff", "#ffd479", "#3a3a46"


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


def _draw(frame, rows, path, keyed, tk) -> None:
    for child in frame.winfo_children():
        child.destroy()

    where = " ".join(path.split()) if path else "root"
    head = tk.Frame(frame, bg=BG)
    head.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 8))
    tk.Label(head, text=f"metamorse · {where}", font=(MONO, 13, "bold"),
             bg=BG, fg=ACCENT).pack(side="left")
    tk.Label(head, text=keyed or "key a letter", font=(MONO, 13, "bold"),
             bg=BG, fg=LIVE if keyed else DIM).pack(side="right")

    for n, (letter, code, label, is_branch) in enumerate(rows, start=1):
        state = _match(code, keyed)
        code_fg, label_fg = _row_colors(state, is_branch)
        marker = "▸" if state == "exact" else " "
        tk.Label(frame, text=marker, font=(MONO, 12), bg=BG,
                 fg=LIVE).grid(row=n, column=0, sticky="w")
        tk.Label(frame, text=f"{code:<6}{letter}", font=(MONO, 12, "bold"),
                 bg=BG, fg=code_fg).grid(row=n, column=1, sticky="w", padx=(2, 10))
        tk.Label(frame, text=f"{'›' if is_branch else ' '} {label}",
                 font=(MONO, 12), bg=BG, fg=label_fg).grid(row=n, column=2, sticky="w")

    tk.Label(frame, text="hold = dash · tap = dot · pause to commit",
             font=(MONO, 10), bg=BG, fg=DIM).grid(
        row=len(rows) + 1, column=0, columnspan=3, sticky="w", pady=(9, 0))


def _reader(queue):
    """stdin on its own thread; a blocking read must never stall the UI."""
    for line in sys.stdin:
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

    def place() -> None:
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        x = (root.winfo_screenwidth() - w) // 2
        y = int(root.winfo_screenheight() * 0.70) - h // 2
        root.geometry(f"+{x}+{y}")

    def poll() -> None:
        try:
            while True:                          # drain: only the last matters
                line = inbox.get_nowait()
                if line is None:
                    return root.destroy()
                message = json.loads(line)
                if message.get("close"):
                    return root.destroy()
                _draw(frame, message["rows"], message.get("path", ""),
                      message.get("keyed", ""), tk)
                place()
        except queuelib.Empty:
            pass
        root.after(25, poll)

    root.after(25, poll)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
