"""The popup. Runs as its own process so tkinter's mainloop never blocks
the event loop; talks over stdin so the daemon can update or dismiss it.

Protocol, one JSON object per line:
    {"rows": [[letter, code, label, is_branch], ...], "path": "t"}
    {"close": true}
"""
from __future__ import annotations

import json
import sys

FONT = ("monospace", 13)
BG, FG, DIM, ACCENT = "#1c1c22", "#e8e8ea", "#7a7a86", "#8fd0ff"


def _draw(frame, rows, path, tk):
    for child in frame.winfo_children():
        child.destroy()
    title = f"metamorse  {path}" if path else "metamorse"
    tk.Label(frame, text=title, font=(FONT[0], FONT[1], "bold"),
             bg=BG, fg=ACCENT, anchor="w").grid(row=0, column=0, columnspan=3,
                                                sticky="w", pady=(0, 6))
    for n, (letter, code, label, is_branch) in enumerate(rows, start=1):
        arrow = "…" if is_branch else "→"
        tk.Label(frame, text=code, font=FONT, bg=BG, fg=ACCENT, anchor="w",
                 width=7).grid(row=n, column=0, sticky="w")
        tk.Label(frame, text=letter, font=(FONT[0], FONT[1], "bold"), bg=BG,
                 fg=FG, width=2).grid(row=n, column=1)
        tk.Label(frame, text=f"{arrow} {label}", font=FONT, bg=BG,
                 fg=FG if not is_branch else DIM,
                 anchor="w").grid(row=n, column=2, sticky="w", padx=(6, 0))


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
    root.overrideredirect(True)                  # no decorations
    frame = tk.Frame(root, bg=BG, padx=14, pady=12)
    frame.pack()

    def place() -> None:
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        x = (root.winfo_screenwidth() - w) // 2
        y = int(root.winfo_screenheight() * 0.72) - h // 2
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
                _draw(frame, message["rows"], message.get("path", ""), tk)
                place()
        except queuelib.Empty:
            pass
        root.after(30, poll)

    root.after(30, poll)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
