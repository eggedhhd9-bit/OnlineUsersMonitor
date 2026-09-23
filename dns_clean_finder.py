"""Compare configured and well-known public DNS resolvers on Windows."""
from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import socket
import struct
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

DOMAINS = ("example.com", "iana.org", "cloudflare.com")
TIMEOUT_SECONDS = 1.7
DNS_CANDIDATES = (
    ("Cloudflare", "1.1.1.1", "معمولی، بدون فیلتر محتوا"),
    ("Cloudflare Malware", "1.1.1.2", "فیلتر بدافزار و فیشینگ"),
    ("Google Public DNS", "8.8.8.8", "DNS عمومی"),
    ("Quad9 Secure", "9.9.9.9", "مسدودسازی دامنه‌های مخرب"),
)


@dataclass
class Result:
    name: str
    address: str
    source: str
    latency_ms: float | None
    successes: int
    total: int
    status: str


def make_query(domain: str) -> tuple[int, bytes]:
    txid = int.from_bytes(os.urandom(2), "big")
    header = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes((len(label),)) + label.encode("ascii") for label in domain.split(".")) + b"\0"
    return txid, header + qname + struct.pack("!HH", 1, 1)


def valid_a_answer(data: bytes, txid: int) -> bool:
    if len(data) < 12:
        return False
    response_id, flags, questions, answers, _, _ = struct.unpack("!HHHHHH", data[:12])
    if response_id != txid or not (flags & 0x8000) or (flags & 0x000F) != 0:
        return False
    if questions < 1 or answers < 1:
        return False
    offset = 12

    def skip_name(pos: int) -> int:
        while pos < len(data):
            length = data[pos]
            if length & 0xC0 == 0xC0:
                return pos + 2
            pos += 1
            if length == 0:
                return pos
            pos += length
        raise ValueError("Malformed DNS name")

    try:
        for _ in range(questions):
            offset = skip_name(offset) + 4
        for _ in range(answers):
            offset = skip_name(offset)
            if offset + 10 > len(data):
                return False
            rtype, rclass, _, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
            offset += 10
            if offset + rdlength > len(data):
                return False
            if rtype == 1 and rclass == 1 and rdlength == 4:
                address = ipaddress.IPv4Address(data[offset:offset + 4])
                return not (address.is_unspecified or address.is_multicast)
            offset += rdlength
    except (ValueError, IndexError, struct.error):
        return False
    return False


def query_one(server: str, domain: str) -> float | None:
    txid, packet = make_query(domain)
    start = time.perf_counter()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(TIMEOUT_SECONDS)
            sock.sendto(packet, (server, 53))
            data, _ = sock.recvfrom(4096)
        if not valid_a_answer(data, txid):
            return None
        return (time.perf_counter() - start) * 1000
    except (OSError, TimeoutError):
        return None


def discover_system_dns() -> list[tuple[str, str]]:
    if os.name != "nt":
        return []
    command = (
        "$ErrorActionPreference='Stop'; "
        "Get-DnsClientServerAddress -AddressFamily IPv4 | "
        "Where-Object { $_.ServerAddresses.Count -gt 0 } | "
        "ForEach-Object { [pscustomobject]@{ Interface=$_.InterfaceAlias; "
        "Servers=$_.ServerAddresses } } | ConvertTo-Json -Compress -Depth 4"
    )
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, errors="replace", timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True,
        )
        if not done.stdout.strip():
            return []
        payload = json.loads(done.stdout)
        if isinstance(payload, dict):
            payload = [payload]
        found: list[tuple[str, str]] = []
        for item in payload:
            addresses = item.get("Servers", [])
            if isinstance(addresses, str):
                addresses = [addresses]
            for address in addresses:
                try:
                    ip = ipaddress.ip_address(address)
                    if ip.version == 4:
                        found.append((str(item.get("Interface", "Windows")), str(ip)))
                except ValueError:
                    continue
        return list(dict.fromkeys(found))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return []


def test_resolver(name: str, address: str, source: str) -> Result:
    latencies = [query_one(address, domain) for domain in DOMAINS]
    good = [value for value in latencies if value is not None]
    median = sorted(good)[len(good) // 2] if good else None
    if len(good) == len(DOMAINS):
        status = "پاسخ کامل"
    elif good:
        status = "پاسخ ناپایدار"
    else:
        status = "بدون پاسخ معتبر"
    return Result(name, address, source, median, len(good), len(DOMAINS), status)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("پاک‌یاب DNS | مقایسه‌گر DNS")
        self.geometry("900x560")
        self.minsize(720, 440)
        self.configure(padx=18, pady=14)

        ttk.Label(self, text="پاک‌یاب DNS", font=("Segoe UI", 20, "bold")).pack(anchor="e")
        ttk.Label(self, text="DNSهای شبکه را از نظر پاسخ معتبر، پایداری و سرعت مقایسه کن.",
                  font=("Segoe UI", 10)).pack(anchor="e", pady=(2, 10))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        self.scan_button = ttk.Button(bar, text="اسکن و مقایسه", command=self.start_scan)
        self.scan_button.pack(side="right")
        self.status = tk.StringVar(value="آمادهٔ بررسی")
        ttk.Label(bar, textvariable=self.status).pack(side="left")

        self.table = ttk.Treeview(self, columns=("dns", "address", "speed", "success", "status", "source"),
                                  show="headings", height=15)
        headers = {"dns": "DNS", "address": "IP", "speed": "سرعت (میلی‌ثانیه)",
                   "success": "پاسخ موفق", "status": "نتیجه", "source": "منبع"}
        widths = {"dns": 180, "address": 130, "speed": 130, "success": 100, "status": 130, "source": 180}
        for col, title in headers.items():
            self.table.heading(col, text=title)
            self.table.column(col, anchor="center", width=widths[col])
        self.table.pack(fill="both", expand=True)

        note = ("روش سنجش: سه نام دامنهٔ عمومی با DNS/UDP بررسی می‌شوند. زمان کمتر و پاسخ‌های موفق بیشتر "
                "امتیاز بهتری می‌گیرند. این آزمون به‌تنهایی نبود سانسور یا فیلتر را تضمین نمی‌کند. "
                "تنظیم DNS ویندوز تغییر داده نمی‌شود.")
        ttk.Label(self, text=note, wraplength=850, justify="right").pack(anchor="e", pady=(10, 0))
        self.after(300, self.start_scan)

    def start_scan(self) -> None:
        if str(self.scan_button["state"]) == "disabled":
            return
        self.scan_button.configure(state="disabled")
        self.status.set("در حال سنجش DNSها…")
        threading.Thread(target=self.scan_worker, daemon=True).start()

    def scan_worker(self) -> None:
        targets: dict[str, tuple[str, str]] = {}
        for interface, address in discover_system_dns():
            targets.setdefault(address, (f"شبکه فعلی · {interface}", address))
        for name, address, note in DNS_CANDIDATES:
            targets.setdefault(address, (name, address, note))

        def test(target: tuple[str, ...]) -> Result:
            if len(target) == 3:
                name, address, note = target
                return test_resolver(name, address, note)
            source, address = target
            return test_resolver(source, address, "تنظیم فعلی Windows")

        results: list[Result] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(test, (*value,) if len(value) == 3 else value)
                       for value in targets.values()]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    continue
        results.sort(key=lambda r: (-r.successes, r.latency_ms if r.latency_ms is not None else float("inf")))
        self.after(0, self.show_results, results)

    def show_results(self, results: list[Result]) -> None:
        for row in self.table.get_children():
            self.table.delete(row)
        for i, result in enumerate(results):
            speed = f"{result.latency_ms:.1f}" if result.latency_ms is not None else "—"
            status = "بهترین نتیجه" if i == 0 and result.successes == result.total else result.status
            self.table.insert("", "end", values=(result.name, result.address, speed,
                                                    f"{result.successes}/{result.total}", status, result.source))
        if results:
            best = results[0]
            self.status.set(f"بررسی تمام شد؛ پیشنهاد: {best.name} ({best.address})" if best.successes
                            else "هیچ DNS پاسخ معتبر نداد؛ اتصال شبکه را بررسی کن.")
        else:
            self.status.set("DNS فعلی پیدا نشد؛ DNSهای عمومی هم بررسی شدند.")
        self.scan_button.configure(state="normal")


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("این برنامه برای Windows 10/11 طراحی شده است.")
    App().mainloop()
