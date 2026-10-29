"""Main window of the desktop application: `netinv gui`.

Built with Tkinter, which ships with Python on Windows and macOS, so the tool
still needs nothing else. The scan runs in a background thread and talks to the
window through a queue (Tkinter must only be touched from the main thread).
"""

from __future__ import annotations

import ipaddress
import queue
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..exporters import EXPORTERS, format_from_path
from ..i18n import Translator
from ..models import Host
from ..ports import COMMON_PORTS, SENSITIVE_PORTS, parse_ports, service_name
from ..scanner import MAX_HOSTS_DEFAULT, expand_targets, guess_local_network, scan
from . import theme
from .view3d import NetworkView3D

# Exports go to App-Scan/rapports/ by default (git ignores it: it holds network data).
REPORTS_DIR = Path(__file__).resolve().parents[2] / "rapports"

# Background of a freshly found row: lit amber, fading back to the table colour.
FLASH_COLORS = [theme.mix(theme.ACCENT, theme.PANEL, 0.62 + i * 0.07) for i in range(6)]
FLASH_STEP_S = 0.12
ANIM_MS = 30
# Ports that usually serve a web interface, in the order we prefer to open them.
WEB_PORTS = [(443, "https"), (8006, "https"), (80, "http"), (8080, "http")]
COLUMNS = ("ip", "hostname", "mac", "vendor", "ports", "latency")
WIDTHS = {"ip": 140, "hostname": 190, "mac": 170, "vendor": 170, "ports": 280, "latency": 110}
POLL_MS = 100


def _sort_key(col: str):
    def key(h: Host):
        if col == "ip":
            return ipaddress.IPv4Address(h.ip)
        if col == "ports":
            return len(h.open_ports)
        if col == "latency":
            return h.latency_ms if h.latency_ms is not None else float("inf")
        value = {"hostname": h.hostname, "mac": h.mac, "vendor": h.vendor}[col]
        return (value is None, (value or "").lower())

    return key


class ThinBar(tk.Frame):
    """A 4 px amber progress line (ttk's clam progress bar cannot be made that thin).

    Same `configure(maximum=, value=)` / `cget()` calls as ttk.Progressbar.
    """

    def __init__(self, master):
        super().__init__(master, height=4, background=theme.FIELD)
        self._fill = tk.Frame(self, background=theme.ACCENT)
        self._max, self._value = 100.0, 0.0
        self._fill.place(x=0, y=0, relheight=1, relwidth=0)

    def configure(self, cnf=None, **kw):
        if "maximum" in kw:
            self._max = max(1e-9, float(kw.pop("maximum")))
        if "value" in kw:
            self._value = float(kw.pop("value"))
        self._fill.place_configure(relwidth=min(1.0, self._value / self._max))
        return super().configure(cnf, **kw) if (cnf or kw) else None

    def cget(self, key):
        if key == "maximum":
            return self._max
        if key == "value":
            return self._value
        return super().cget(key)


class App:
    def __init__(self, root: tk.Tk, lang: str | None = None):
        self.root = root
        self.t = Translator(lang)
        self.hosts: dict[str, Host] = {}
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.started = 0.0
        self.sort_col, self.sort_desc = "ip", False
        self.last_settings: tuple = (list(COMMON_PORTS), 0.5, True, True)
        self.progress_target = 0.0
        self.flash: dict[str, float] = {}  # ip -> time the row appeared
        self.row_tags: dict[str, tuple] = {}

        theme.apply(root)
        root.title(self.t("gui_title"))
        # As big as asked, but never larger than the screen (taskbar included)
        width = min(1180, root.winfo_screenwidth() - 60)
        height = min(880, root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}+{max(0, (root.winfo_screenwidth() - width) // 2)}+20")
        root.minsize(min(860, width), min(600, height))
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(POLL_MS, self._poll)
        root.after(ANIM_MS, self._animate)

    # -- layout ---------------------------------------------------------------
    def _build(self) -> None:
        t = self.t
        outer = ttk.Frame(self.root, padding=(24, 18, 24, 14))
        outer.pack(fill="both", expand=True)

        # Header: what the tool is, in one sentence
        ttk.Label(outer, text=t("gui_title"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text=t("gui_subtitle"), style="Muted.TLabel").pack(anchor="w", pady=(2, 16))

        # Scan settings: each field has its label above it
        self.target_var = tk.StringVar(value=guess_local_network())
        self.ports_var = tk.StringVar(value=",".join(map(str, COMMON_PORTS)))
        self.timeout_var = tk.StringVar(value="0.5")
        self.ping_var = tk.BooleanVar(value=True)
        self.dns_var = tk.BooleanVar(value=True)

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text=t("gui_target"), style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text=t("gui_ports"), style="Field.TLabel").grid(
            row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(form, text=t("gui_timeout"), style="Field.TLabel").grid(
            row=0, column=2, sticky="w", padx=(12, 0))

        target = ttk.Entry(form, textvariable=self.target_var, width=22, style="Mono.TEntry",
                           font=theme.MONO)
        target.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        target.bind("<Return>", lambda e: self._start())
        ttk.Entry(form, textvariable=self.ports_var, style="Mono.TEntry", font=theme.MONO).grid(
            row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        ttk.Spinbox(form, from_=0.1, to=10, increment=0.1, width=5, font=theme.MONO,
                    textvariable=self.timeout_var).grid(row=1, column=2, sticky="w", padx=(12, 0),
                                                        pady=(4, 0))
        actions = ttk.Frame(form)
        actions.grid(row=1, column=3, sticky="e", padx=(20, 0), pady=(4, 0))
        self.start_btn = ttk.Button(actions, text=t("gui_start"), style="Primary.TButton",
                                    command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text=t("gui_stop"), command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        ttk.Label(form, text=t("gui_target_hint"), style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        opts = ttk.Frame(form)
        opts.grid(row=2, column=1, columnspan=3, sticky="w", padx=(12, 0), pady=(6, 0))
        ttk.Checkbutton(opts, text=t("gui_ping"), variable=self.ping_var).pack(side="left")
        ttk.Checkbutton(opts, text=t("gui_dns"), variable=self.dns_var).pack(side="left", padx=(18, 0))

        # Progress: a thin line and one status sentence
        prog = ttk.Frame(outer)
        prog.pack(fill="x", pady=(18, 12))
        self.progress = ThinBar(prog)
        self.progress.pack(fill="x")
        self.status_var = tk.StringVar(value=t("gui_ready"))
        ttk.Label(prog, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(8, 0))

        # 3D view above the results; the divider between them can be dragged
        panes = ttk.PanedWindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True)
        self.view = NetworkView3D(panes, t, on_select=self._select_from_view,
                                  on_activate=self._activate, height=360)
        panes.add(self.view, weight=3)
        results = ttk.Frame(panes)
        panes.add(results, weight=2)

        bar = ttk.Frame(results)
        bar.pack(fill="x", pady=(10, 8))
        ttk.Label(bar, text=t("gui_filter")).pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._render())
        ttk.Entry(bar, textvariable=self.filter_var, width=30).pack(side="left", padx=(8, 14))
        self.count_var = tk.StringVar(value=t("gui_count", shown=0, total=0))
        ttk.Label(bar, textvariable=self.count_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text=t("gui_export"), command=self._export).pack(side="right")

        table = ttk.Frame(results, style="Panel.TFrame")
        table.pack(fill="both", expand=True)
        # few rows requested: the 3D view gets the space first
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", selectmode="browse",
                                 height=6)
        heads = {"ip": "col_ip", "hostname": "col_hostname", "mac": "col_mac",
                 "vendor": "col_vendor", "ports": "col_ports", "latency": "col_latency"}
        for col in COLUMNS:
            self.tree.heading(col, text=t(heads[col]), command=lambda c=col: self._sort_by(c),
                              anchor="e" if col == "latency" else "w")
            self.tree.column(col, width=WIDTHS[col], anchor="e" if col == "latency" else "w",
                             stretch=col in ("hostname", "vendor", "ports"))
        self.tree.tag_configure("odd", background=theme.PANEL_ALT)
        self.tree.tag_configure("risky", background=theme.DANGER_ROW)
        for i, color in enumerate(FLASH_COLORS):
            self.tree.tag_configure(f"flash{i}", background=color)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.menu = theme.menu(self.root)

        ttk.Label(outer, text=t("gui_legend"), style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(outer, text=t("gui_responsible"), style="Muted.TLabel").pack(anchor="w")
        self._update_headings()

    # -- scan -----------------------------------------------------------------
    def _read_settings(self) -> tuple | None:
        t = self.t
        target = self.target_var.get().strip() or guess_local_network()
        self.target_var.set(target)
        try:
            targets = expand_targets(target, max_hosts=MAX_HOSTS_DEFAULT)
        except ValueError as exc:
            messagebox.showerror(t("gui_title"), t("error_target", error=exc))
            return None
        try:
            spec = self.ports_var.get().strip()
            ports = parse_ports(spec) if spec else list(COMMON_PORTS)
        except ValueError as exc:
            messagebox.showerror(t("gui_title"), t("error_ports", error=exc))
            return None
        try:
            timeout = float(self.timeout_var.get().replace(",", "."))
            if not 0.1 <= timeout <= 10:
                raise ValueError
        except ValueError:
            messagebox.showerror(t("gui_title"), t("gui_error_timeout"))
            return None
        return target, targets, ports, timeout, self.ping_var.get(), self.dns_var.get()

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        settings = self._read_settings()
        if settings is None:
            return
        target, targets, ports, timeout, ping, dns = settings
        self.last_settings = (ports, timeout, ping, dns)
        self.hosts.clear()
        self.flash.clear()
        self.view.clear()
        self.view.set_scanning(True)
        self._render()
        self.stop.clear()
        self.progress.configure(maximum=len(targets), value=0)
        self.progress_target = 0.0
        self.status_var.set(self.t("scanning", count=len(targets), target=target))
        self._set_running(True)
        self.started = time.perf_counter()
        self.worker = threading.Thread(target=self._run, args=(targets, ports, timeout, ping, dns),
                                       daemon=True)
        self.worker.start()

    def _run(self, targets, ports, timeout, ping, dns) -> None:
        try:
            hosts = scan(
                targets, ports=ports, timeout=timeout, use_ping=ping, resolve=dns,
                on_progress=lambda done, total: self.events.put(("progress", done, total)),
                on_host=lambda host: self.events.put(("host", host)),
                stop=self.stop,
            )
            self.events.put(("done", hosts))
        except Exception as exc:  # noqa: BLE001 - shown to the user, never silent
            self.events.put(("error", exc))

    def _stop(self) -> None:
        self.stop.set()
        self.stop_btn.configure(state="disabled")
        self.status_var.set(self.t("gui_stopping"))

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def _rescan(self, ip: str) -> None:
        ports, timeout, ping, dns = self.last_settings
        self.status_var.set(self.t("gui_rescanning", ip=ip))

        def job():
            try:
                found = scan([ip], ports=ports, timeout=timeout, use_ping=ping, resolve=dns,
                             include_down=True)
                self.events.put(("rescan", ip, found[0] if found else None))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("error", exc))

        threading.Thread(target=job, daemon=True).start()

    def _poll(self) -> None:
        t = self.t
        dirty = False
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    done, total = event[1], event[2]
                    self.progress_target = done  # the bar glides there in _animate
                    self.view.progress = done / total
                    if not self.stop.is_set():
                        self.status_var.set(t("gui_progress", done=done, total=total,
                                              found=len(self.hosts)))
                elif kind == "host":
                    host = event[1]
                    self.hosts[host.ip] = host
                    self.flash[host.ip] = time.perf_counter()
                    self.view.add_host(host)
                    dirty = True
                elif kind == "done":
                    # Final list: same hosts, now with MAC address and vendor from ARP.
                    self.hosts = {h.ip: h for h in event[1]}
                    self.view.set_hosts(event[1])
                    self.view.set_scanning(False)
                    self.progress_target = self.progress.cget("maximum")
                    dirty = True
                    count, seconds = len(self.hosts), time.perf_counter() - self.started
                    if self.stop.is_set():
                        self.status_var.set(t("gui_stopped", count=count))
                    elif count:
                        self.status_var.set(t("found", count=count, seconds=f"{seconds:.1f}"))
                    else:
                        self.status_var.set(t("none_found"))
                    self._set_running(False)
                elif kind == "rescan":
                    ip, host = event[1], event[2]
                    if host is not None and host.alive:
                        self.hosts[ip] = host
                        self.flash[ip] = time.perf_counter()
                        self.status_var.set(t("gui_rescanned", ip=ip))
                    else:
                        self.hosts.pop(ip, None)
                        self.status_var.set(t("gui_gone", ip=ip))
                    self.view.set_hosts(list(self.hosts.values()))
                    dirty = True
                elif kind == "error":
                    self._set_running(False)
                    self.view.set_scanning(False)
                    self.status_var.set(t("gui_error_scan", error=event[1]))
                    messagebox.showerror(t("gui_title"), t("gui_error_scan", error=event[1]))
        except queue.Empty:
            pass
        if dirty:
            self._render()
        self.root.after(POLL_MS, self._poll)

    # -- table ----------------------------------------------------------------
    def _values(self, h: Host) -> tuple:
        dash = self.t("unknown")
        ports = ", ".join(f"{p}/{service_name(p)}" for p in h.open_ports)
        latency = f"{h.latency_ms:.1f}" if h.latency_ms is not None else dash
        return (h.ip, h.hostname or dash, h.mac or dash, h.vendor or dash, ports or dash, latency)

    def _visible(self) -> list[Host]:
        q = self.filter_var.get().strip().lower()
        rows = [h for h in self.hosts.values()
                if not q or q in " ".join(self._values(h)).lower()]
        rows.sort(key=_sort_key(self.sort_col), reverse=self.sort_desc)
        return rows

    def _render(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        rows = self._visible()
        self.row_tags.clear()
        for i, h in enumerate(rows):
            tag = "risky" if SENSITIVE_PORTS & set(h.open_ports) else ("odd" if i % 2 else "")
            self.row_tags[h.ip] = (tag,) if tag else ()
            self.tree.insert("", "end", iid=h.ip, values=self._values(h),
                             tags=self._flash_tag(h.ip) or self.row_tags[h.ip])
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self.count_var.set(self.t("gui_count", shown=len(rows), total=len(self.hosts)))
        q = self.filter_var.get().strip()
        self.view.set_visible({h.ip for h in rows} if q else None)

    # -- motion -------------------------------------------------------------------
    def _flash_tag(self, ip: str) -> tuple:
        born = self.flash.get(ip)
        if born is None:
            return ()
        step = int((time.perf_counter() - born) / FLASH_STEP_S)
        return (f"flash{step}",) if step < len(FLASH_COLORS) else ()

    def _animate(self) -> None:
        # progress bar glides to its target instead of jumping
        value = float(self.progress.cget("value"))
        if abs(self.progress_target - value) > 0.01:
            self.progress.configure(value=value + (self.progress_target - value) * 0.25)
        # freshly found rows fade from violet to their normal colour
        for ip in list(self.flash):
            tag = self._flash_tag(ip)
            if self.tree.exists(ip):
                self.tree.item(ip, tags=tag or self.row_tags.get(ip, ()))
            if not tag:
                del self.flash[ip]
        self.root.after(ANIM_MS, self._animate)

    def _on_tree_select(self, _event=None) -> None:
        sel = self.tree.selection()
        self.view.select(sel[0] if sel else None)

    def _select_from_view(self, ip: str) -> None:
        if self.tree.exists(ip):
            self.tree.selection_set(ip)
            self.tree.see(ip)

    def _activate(self, ip: str) -> None:
        host = self.hosts.get(ip)
        if not host:
            return
        url = self._web_url(host)
        if url:
            webbrowser.open(url)
        else:
            self._copy(host.ip)

    def _sort_by(self, col: str) -> None:
        self.sort_desc = not self.sort_desc if self.sort_col == col else False
        self.sort_col = col
        self._update_headings()
        self._render()

    def _update_headings(self) -> None:
        heads = {"ip": "col_ip", "hostname": "col_hostname", "mac": "col_mac",
                 "vendor": "col_vendor", "ports": "col_ports", "latency": "col_latency"}
        for col in COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if col == self.sort_col else ""
            self.tree.heading(col, text=self.t(heads[col]) + arrow)

    # -- row actions ----------------------------------------------------------
    def _web_url(self, h: Host) -> str | None:
        for port, scheme in WEB_PORTS:
            if port in h.open_ports:
                default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
                return f"{scheme}://{h.ip}" + ("" if default else f":{port}")
        return None

    def _copy(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.status_var.set(self.t("gui_copied", value=value))

    def _on_double_click(self, event) -> None:
        self._activate(self.tree.identify_row(event.y))

    def _on_right_click(self, event) -> None:
        ip = self.tree.identify_row(event.y)
        host = self.hosts.get(ip)
        if not host:
            return
        t = self.t
        self.tree.selection_set(ip)
        self.menu.delete(0, "end")
        self.menu.add_command(label=t("gui_copy_ip"), command=lambda: self._copy(host.ip))
        self.menu.add_command(label=t("gui_copy_mac"), command=lambda: self._copy(host.mac or ""),
                              state="normal" if host.mac else "disabled")
        url = self._web_url(host)
        self.menu.add_command(label=t("gui_open_browser") + (f"  ({url})" if url else ""),
                              command=lambda: webbrowser.open(url), state="normal" if url else "disabled")
        self.menu.add_separator()
        running = bool(self.worker and self.worker.is_alive())
        self.menu.add_command(label=t("gui_rescan"), command=lambda: self._rescan(host.ip),
                              state="disabled" if running else "normal")
        self.menu.tk_popup(event.x_root, event.y_root)

    # -- export ---------------------------------------------------------------
    def _export(self) -> None:
        t = self.t
        hosts = self._visible()
        if not hosts:
            messagebox.showinfo(t("gui_title"), t("gui_nothing_to_export"))
            return
        REPORTS_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".html", initialdir=str(REPORTS_DIR),
            initialfile=f"inventaire-reseau-{time.strftime('%Y-%m-%d_%H-%M')}.html",
            filetypes=[("HTML", "*.html"), ("CSV", "*.csv"), ("JSON", "*.json"), ("Texte", "*.txt")],
        )
        if not path:
            return
        fmt = format_from_path(path) or "html"
        Path(path).write_text(EXPORTERS[fmt](hosts, t), encoding="utf-8")
        self.status_var.set(t("saved", path=path))
        if fmt == "html":
            webbrowser.open(Path(path).resolve().as_uri())

    def _close(self) -> None:
        self.stop.set()
        self.root.destroy()


def run(lang: str | None = None) -> int:
    try:  # sharp text on high-DPI Windows screens
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError, ImportError):
        pass
    root = tk.Tk()
    App(root, lang)
    root.mainloop()
    return 0
