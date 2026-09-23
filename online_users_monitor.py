"""Local Windows session monitor with a small Tkinter UI."""
from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

INTERVAL_MS = 30_000


def data_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    folder = Path(base) / "OnlineUsersMonitor"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


LOG_FILE = data_directory() / "online-users.csv"


def read_sessions() -> list[tuple[str, str, str]]:
    """Return (user, session, state) from quser, tolerating localized headers."""
    try:
        result = subprocess.run(["quser"], capture_output=True, text=True,
                                errors="replace", timeout=8, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"اجرای quser ناموفق بود: {exc}") from exc
    if result.returncode and not result.stdout.strip():
        detail = result.stderr.strip() or "فرمان quser خروجی نداد"
        raise RuntimeError(detail)

    rows: list[tuple[str, str, str]] = []
    # quser columns are separated by runs of spaces. Strip the optional current-session marker.
    for line in result.stdout.splitlines()[1:]:
        line = line.strip().lstrip("> ")
        if not line:
            continue
        cols = re.split(r"\s{2,}", line)
        # Typical columns: USERNAME, SESSIONNAME (optional), ID, STATE, IDLE TIME, LOGON TIME
        # For a session with no SESSIONNAME, ID is the second column.
        if len(cols) < 4:
            continue
        user = cols[0]
        if len(cols) >= 5 and cols[1].isdigit():
            session, state = "(بدون نام)", cols[2]
        elif len(cols) >= 4:
            session, state = cols[1], cols[3]
        else:
            continue
        rows.append((user, session, state))
    return rows


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("بررسی کاربران آنلاین ویندوز")
        self.geometry("660x400")
        self.minsize(520, 300)
        self.configure(padx=14, pady=12)

        ttk.Label(self, text="نشست‌های فعال این رایانه", font=("Segoe UI", 15, "bold")).pack(anchor="e")
        self.status = tk.StringVar(value="در حال بررسی…")
        ttk.Label(self, textvariable=self.status).pack(anchor="e", pady=(4, 10))

        self.table = ttk.Treeview(self, columns=("user", "session", "state"), show="headings", height=11)
        self.table.heading("user", text="کاربر")
        self.table.heading("session", text="نشست")
        self.table.heading("state", text="وضعیت")
        self.table.column("user", anchor="center", width=210)
        self.table.column("session", anchor="center", width=210)
        self.table.column("state", anchor="center", width=150)
        self.table.pack(fill="both", expand=True)

        footer = ttk.Frame(self)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="بررسی دوباره", command=self.refresh).pack(side="right")
        ttk.Label(footer, text=f"ثبت گزارش: {LOG_FILE}", wraplength=450).pack(side="left", anchor="w")
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = read_sessions()
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            new_file = not LOG_FILE.exists()
            with LOG_FILE.open("a", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                if new_file:
                    writer.writerow(["time", "computer", "user", "session", "state"])
                for user, session, state in rows:
                    writer.writerow([now, os.environ.get("COMPUTERNAME", ""), user, session, state])
            for item in self.table.get_children():
                self.table.delete(item)
            for row in rows:
                self.table.insert("", "end", values=row)
            self.status.set(f"{len(rows)} نشست پیدا شد | آخرین بررسی: {datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            self.status.set(f"خطا: {exc}")
        self.after(INTERVAL_MS, self.refresh)


if __name__ == "__main__":
    if os.name != "nt":
        print("این برنامه برای Windows 10/11 طراحی شده است.", file=sys.stderr)
        raise SystemExit(1)
    try:
        App().mainloop()
    except Exception as exc:
        messagebox.showerror("خطای برنامه", str(exc))
