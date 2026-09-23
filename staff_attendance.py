"""Local staff registry and attendance tracker for Windows."""
from __future__ import annotations

import csv
import os
import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


def default_db_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "StaffAttendance"
    root.mkdir(parents=True, exist_ok=True)
    return root / "attendance.sqlite3"


DB_PATH = default_db_path()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_code TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                check_in TEXT NOT NULL,
                check_out TEXT
            );
            CREATE INDEX IF NOT EXISTS attendance_employee_time
                ON attendance(employee_id, check_in);
        """)


def add_employee(code: str, full_name: str, department: str = "", db_path: Path = DB_PATH) -> int:
    code, full_name, department = code.strip(), full_name.strip(), department.strip()
    if not code or not full_name:
        raise ValueError("کد پرسنلی و نام کارمند الزامی است.")
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO employees(employee_code,full_name,department,created_at) VALUES(?,?,?,?)",
            (code, full_name, department, datetime.now().astimezone().isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def list_employees(db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute("""
            SELECT e.id, e.employee_code, e.full_name, e.department,
                   CASE WHEN EXISTS(SELECT 1 FROM attendance a
                                    WHERE a.employee_id=e.id AND a.check_out IS NULL)
                        THEN 'حاضر' ELSE 'خارج' END AS attendance_state
            FROM employees e WHERE e.active=1 ORDER BY e.employee_code COLLATE NOCASE
        """).fetchall()


def record_punch(employee_id: int, action: str, db_path: Path = DB_PATH) -> str:
    if action not in {"in", "out"}:
        raise ValueError("نوع ثبت نامعتبر است.")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        employee = conn.execute("SELECT active FROM employees WHERE id=?", (employee_id,)).fetchone()
        if employee is None or not employee["active"]:
            raise ValueError("کارمند فعال پیدا نشد.")
        open_shift = conn.execute(
            "SELECT id FROM attendance WHERE employee_id=? AND check_out IS NULL ORDER BY id DESC LIMIT 1",
            (employee_id,),
        ).fetchone()
        if action == "in":
            if open_shift:
                raise ValueError("برای این کارمند ورود ثبت‌شده و خروج ثبت‌نشده وجود دارد.")
            conn.execute("INSERT INTO attendance(employee_id,check_in) VALUES(?,?)", (employee_id, now))
        else:
            if not open_shift:
                raise ValueError("برای این کارمند ورود بازی ثبت نشده است.")
            conn.execute("UPDATE attendance SET check_out=? WHERE id=?", (now, open_shift["id"]))
    return now


def attendance_rows(day: str = "", db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    query = """
        SELECT a.id, e.employee_code, e.full_name, e.department, a.check_in, a.check_out
        FROM attendance a JOIN employees e ON e.id=a.employee_id
    """
    params: tuple[str, ...] = ()
    if day:
        query += " WHERE substr(a.check_in,1,10)=?"
        params = (day,)
    query += " ORDER BY a.check_in DESC, e.employee_code COLLATE NOCASE"
    with connect(db_path) as conn:
        return conn.execute(query, params).fetchall()


def display_time(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d  %H:%M:%S")
    except ValueError:
        return value


def work_duration(start: str, end: str | None) -> str:
    if not end:
        return "در حال کار"
    try:
        seconds = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except ValueError:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours:02d}:{minutes:02d}"


class AttendanceApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        initialize()
        self.title("سامانهٔ ثبت ورود و خروج پرسنل")
        self.geometry("1050x680")
        self.minsize(850, 560)
        self.configure(padx=16, pady=12)
        self.employee_ids: dict[str, int] = {}

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="حضور و غیاب پرسنل", font=("Segoe UI", 19, "bold")).pack(side="right")
        self.clock = tk.StringVar()
        ttk.Label(header, textvariable=self.clock, font=("Segoe UI", 11)).pack(side="left")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        self.attendance_tab = ttk.Frame(self.tabs, padding=12)
        self.employees_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.attendance_tab, text="ثبت تردد و گزارش")
        self.tabs.add(self.employees_tab, text="ثبت‌نام پرسنل")
        self._build_attendance_tab()
        self._build_employees_tab()

        self.status = tk.StringVar(value=f"اطلاعات فقط روی همین رایانه ذخیره می‌شود | {DB_PATH}")
        ttk.Label(self, textvariable=self.status, wraplength=1000).pack(anchor="e", pady=(8, 0))
        self.refresh_all()
        self._tick_clock()

    def _build_attendance_tab(self) -> None:
        punch = ttk.LabelFrame(self.attendance_tab, text="ثبت ورود یا خروج", padding=10)
        punch.pack(fill="x", pady=(0, 10))
        ttk.Label(punch, text="کارمند:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.employee_choice = tk.StringVar()
        self.employee_box = ttk.Combobox(punch, textvariable=self.employee_choice, state="readonly", width=42)
        self.employee_box.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.employee_box.bind("<<ComboboxSelected>>", lambda _event: self._update_selected_status())
        ttk.Button(punch, text="ثبت ورود", command=lambda: self.punch("in")).grid(row=0, column=2, padx=7, pady=5)
        ttk.Button(punch, text="ثبت خروج", command=lambda: self.punch("out")).grid(row=0, column=3, padx=7, pady=5)
        self.selected_state = tk.StringVar(value="کارمند را انتخاب کنید")
        ttk.Label(punch, textvariable=self.selected_state).grid(row=1, column=0, columnspan=4, sticky="e", padx=5)
        punch.columnconfigure(1, weight=1)

        current = ttk.LabelFrame(self.attendance_tab, text="وضعیت فعلی پرسنل", padding=8)
        current.pack(fill="both", expand=True, pady=(0, 10))
        self.people_table = ttk.Treeview(current, columns=("code", "name", "department", "state"),
                                         show="headings", height=7)
        self._setup_table(self.people_table, {
            "code": ("کد پرسنلی", 130), "name": ("نام و نام خانوادگی", 280),
            "department": ("واحد", 220), "state": ("وضعیت", 120),
        })
        self.people_table.pack(fill="both", expand=True)

        history_box = ttk.LabelFrame(self.attendance_tab, text="گزارش ورود و خروج", padding=8)
        history_box.pack(fill="both", expand=True)
        filter_bar = ttk.Frame(history_box)
        filter_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(filter_bar, text="تاریخ (YYYY-MM-DD):").pack(side="right", padx=4)
        self.date_filter = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        ttk.Entry(filter_bar, textvariable=self.date_filter, width=14, justify="center").pack(side="right", padx=4)
        ttk.Button(filter_bar, text="نمایش", command=self.refresh_history).pack(side="right", padx=4)
        ttk.Button(filter_bar, text="همهٔ سوابق", command=self.show_all_history).pack(side="right", padx=4)
        ttk.Button(filter_bar, text="خروجی CSV", command=self.export_csv).pack(side="left", padx=4)
        self.history_table = ttk.Treeview(history_box,
            columns=("code", "name", "department", "in", "out", "duration"), show="headings", height=8)
        self._setup_table(self.history_table, {
            "code": ("کد", 90), "name": ("کارمند", 180), "department": ("واحد", 120),
            "in": ("تاریخ و ساعت ورود", 210), "out": ("تاریخ و ساعت خروج", 210),
            "duration": ("مدت حضور", 110),
        })
        self.history_table.pack(fill="both", expand=True)

    def _build_employees_tab(self) -> None:
        form = ttk.LabelFrame(self.employees_tab, text="ثبت‌نام کارمند جدید", padding=12)
        form.pack(fill="x", pady=(0, 12))
        self.code_var, self.name_var, self.department_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        fields = (("کد پرسنلی *", self.code_var), ("نام و نام خانوادگی *", self.name_var),
                  ("واحد / سمت", self.department_var))
        for col, (label, variable) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=col, padx=5, pady=(0, 4), sticky="e")
            ttk.Entry(form, textvariable=variable, justify="right", width=28).grid(row=1, column=col, padx=5, pady=4, sticky="ew")
            form.columnconfigure(col, weight=1)
        ttk.Button(form, text="ثبت کارمند", command=self.add_person).grid(row=1, column=3, padx=8)

        ttk.Label(self.employees_tab,
                  text="فهرست پرسنل فعال. سوابق تردد پس از ثبت کارمند در برگهٔ «ثبت تردد و گزارش» نمایش داده می‌شود.",
                  wraplength=950).pack(anchor="e", pady=(4, 8))
        self.employee_table = ttk.Treeview(self.employees_tab,
            columns=("code", "name", "department", "state"), show="headings", height=18)
        self._setup_table(self.employee_table, {
            "code": ("کد پرسنلی", 170), "name": ("نام و نام خانوادگی", 340),
            "department": ("واحد / سمت", 260), "state": ("وضعیت", 150),
        })
        self.employee_table.pack(fill="both", expand=True)

    @staticmethod
    def _setup_table(table: ttk.Treeview, columns: dict[str, tuple[str, int]]) -> None:
        for key, (heading, width) in columns.items():
            table.heading(key, text=heading)
            table.column(key, width=width, anchor="center", stretch=True)

    def _tick_clock(self) -> None:
        self.clock.set(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(1000, self._tick_clock)

    def refresh_all(self) -> None:
        previous = self.employee_choice.get()
        employees = list_employees()
        self.employee_ids = {f"{r['employee_code']}  |  {r['full_name']}": r["id"] for r in employees}
        self.employee_box["values"] = list(self.employee_ids)
        if previous in self.employee_ids:
            self.employee_choice.set(previous)
        elif self.employee_ids:
            self.employee_choice.set(next(iter(self.employee_ids)))
        else:
            self.employee_choice.set("")
        for table in (self.people_table, self.employee_table):
            for item in table.get_children():
                table.delete(item)
            for row in employees:
                values = (row["employee_code"], row["full_name"], row["department"], row["attendance_state"])
                table.insert("", "end", values=values)
        self.refresh_history()
        self._update_selected_status()

    def _update_selected_status(self) -> None:
        employee_id = self.employee_ids.get(self.employee_choice.get())
        if employee_id is None:
            self.selected_state.set("ابتدا در برگهٔ ثبت‌نام، کارمند اضافه کنید.")
            return
        row = next((r for r in list_employees() if r["id"] == employee_id), None)
        self.selected_state.set(f"وضعیت فعلی: {row['attendance_state']}" if row else "کارمند فعال پیدا نشد.")

    def add_person(self) -> None:
        try:
            add_employee(self.code_var.get(), self.name_var.get(), self.department_var.get())
            self.code_var.set("")
            self.name_var.set("")
            self.department_var.set("")
            self.status.set("کارمند ثبت شد.")
            self.refresh_all()
        except sqlite3.IntegrityError:
            messagebox.showerror("کد تکراری", "این کد پرسنلی قبلاً ثبت شده است.", parent=self)
        except ValueError as exc:
            messagebox.showwarning("اطلاعات ناقص", str(exc), parent=self)
        except sqlite3.Error as exc:
            messagebox.showerror("خطای پایگاه داده", str(exc), parent=self)

    def punch(self, action: str) -> None:
        employee_id = self.employee_ids.get(self.employee_choice.get())
        if employee_id is None:
            messagebox.showwarning("انتخاب کارمند", "ابتدا یک کارمند را انتخاب کنید.", parent=self)
            return
        try:
            timestamp = record_punch(employee_id, action)
            label = "ورود" if action == "in" else "خروج"
            self.status.set(f"{label} ثبت شد: {display_time(timestamp)}")
            self.refresh_all()
        except ValueError as exc:
            messagebox.showwarning("ثبت تردد", str(exc), parent=self)
        except sqlite3.Error as exc:
            messagebox.showerror("خطای پایگاه داده", str(exc), parent=self)

    def refresh_history(self) -> None:
        day = self.date_filter.get().strip()
        if day:
            try:
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                self.status.set("تاریخ باید به شکل YYYY-MM-DD باشد.")
                return
        for item in self.history_table.get_children():
            self.history_table.delete(item)
        for row in attendance_rows(day):
            self.history_table.insert("", "end", values=(
                row["employee_code"], row["full_name"], row["department"],
                display_time(row["check_in"]), display_time(row["check_out"]),
                work_duration(row["check_in"], row["check_out"]),
            ))

    def show_all_history(self) -> None:
        self.date_filter.set("")
        self.refresh_history()

    def export_csv(self) -> None:
        day = self.date_filter.get().strip()
        if day:
            try:
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                messagebox.showwarning("تاریخ نامعتبر", "تاریخ را به شکل YYYY-MM-DD وارد کنید.", parent=self)
                return
        rows = attendance_rows(day)
        if not rows:
            messagebox.showinfo("خروجی CSV", "برای این بازه سابقه‌ای پیدا نشد.", parent=self)
            return
        initial = f"attendance-{day or 'all'}.csv"
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
            initialfile=initial, filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(["کد پرسنلی", "نام", "واحد", "ورود", "خروج", "مدت حضور"])
                for row in rows:
                    writer.writerow([row["employee_code"], row["full_name"], row["department"],
                                     display_time(row["check_in"]), display_time(row["check_out"]),
                                     work_duration(row["check_in"], row["check_out"])])
            self.status.set(f"گزارش ذخیره شد: {path}")
        except OSError as exc:
            messagebox.showerror("ذخیرهٔ گزارش", str(exc), parent=self)


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("این برنامه برای Windows 10/11 طراحی شده است.")
    AttendanceApp().mainloop()
