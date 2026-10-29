"""Design tokens for the desktop app: every colour and font lives here.

Idea: a patch panel. Graphite surfaces like a rack, one amber accent like a
link LED, and device kinds coloured like the patch cables that reach them
(uplink amber, servers blue, workstations green, printers white, misc grey).
Red is reserved for one meaning only: a sensitive port is open.

Contrast (WCAG): TEXT on BG 15:1, MUTED on BG 7:1, ACCENT on BG 9.8:1,
ON_ACCENT on ACCENT 10:1, TEXT on a red or selected row 10:1 or more.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# -- colours ------------------------------------------------------------------
BG = "#14171a"          # window
PANEL = "#1b1f23"       # table, cards
PANEL_ALT = "#1f2428"   # every other table row
RAISED = "#262c31"      # secondary buttons, headings on hover
RAISED_HOVER = "#30373d"
FIELD = "#0f1214"       # inputs, 3D stage
LINE = "#2f363c"
GRID = "#262d33"        # 3D floor
TEXT = "#e8ebe9"
MUTED = "#9aa3a8"
ACCENT = "#ffb020"
ACCENT_HOVER = "#ffc24f"
ACCENT_PRESSED = "#e69a10"
ON_ACCENT = "#1a1405"
DANGER = "#ff5d5d"
DANGER_ROW = "#3a2224"
SELECT = "#3b3220"      # selected row: amber, dimmed

# Device kinds, coloured like their patch cable.
KIND_COLORS = {
    "router": ACCENT,
    "server": "#4da3ff",
    "pc": "#3ccf91",
    "printer": "#e0e4e2",
    "device": "#8f9aa3",
}

# -- type: two families, the monospace one only for network data ----------------
BODY = ("Segoe UI", 10)
SMALL = ("Segoe UI", 9)
STRONG = ("Segoe UI Semibold", 10)
TITLE = ("Segoe UI Semibold", 17)
MONO = ("Consolas", 10)  # replaced by Cascadia Mono when installed (see apply)


def mix(a: str, b: str, k: float) -> str:
    """Blend colour a towards b (k = 0 -> a, 1 -> b). Tk has no transparency."""
    k = 0.0 if k < 0 else 1.0 if k > 1 else k
    ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return f"#{round(ra + (rb - ra) * k):02x}{round(ga + (gb - ga) * k):02x}{round(ba + (bb - ba) * k):02x}"


def reduced_motion() -> bool:
    """True when Windows "Show animations" is off (Settings > Accessibility > Visual effects)."""
    try:
        import ctypes

        enabled = ctypes.c_bool(True)
        # SPI_GETCLIENTAREAANIMATION
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return not enabled.value
    except (AttributeError, OSError, ImportError):
        return False


def _dark_title_bar(root: tk.Tk) -> None:
    """Match the Windows title bar to the dark window (Windows 10 20H1+)."""
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
    except (AttributeError, OSError, ImportError):
        pass


def apply(root: tk.Tk) -> None:
    """Style every ttk widget from the tokens above."""
    global MONO
    if "Cascadia Mono" in tkfont.families(root):
        MONO = ("Cascadia Mono", 10)

    root.configure(background=BG)  # no "*Font" option: it would override the ttk styles below
    _dark_title_bar(root)

    s = ttk.Style(root)
    s.theme_use("clam")  # the only built-in theme that lets us recolour everything
    s.configure(".", background=BG, foreground=TEXT, font=BODY, bordercolor=LINE,
                lightcolor=BG, darkcolor=BG, troughcolor=FIELD, fieldbackground=FIELD,
                selectbackground=SELECT, selectforeground=TEXT, insertcolor=TEXT,
                focuscolor=ACCENT)
    s.configure("TFrame", background=BG)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Title.TLabel", font=TITLE)
    s.configure("Muted.TLabel", foreground=MUTED, font=SMALL)
    s.configure("Field.TLabel", foreground=MUTED, font=SMALL)
    s.configure("Status.TLabel", foreground=TEXT, font=BODY)

    # Inputs: dark well, amber border on focus
    s.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, padding=(8, 6),
                bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
          fieldbackground=[("disabled", BG)], foreground=[("disabled", MUTED)])
    s.configure("Mono.TEntry", font=MONO)
    s.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, background=RAISED,
                arrowcolor=TEXT, padding=(6, 5), bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD,
                arrowsize=12)
    s.map("TSpinbox", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
          background=[("active", RAISED_HOVER)])

    # Buttons: one primary style (amber), one secondary style (raised graphite)
    s.configure("TButton", background=RAISED, foreground=TEXT, padding=(16, 7), borderwidth=1,
                bordercolor=LINE, lightcolor=RAISED, darkcolor=RAISED, focusthickness=1,
                focuscolor=ACCENT, relief="flat")
    s.map("TButton",
          background=[("disabled", BG), ("pressed", LINE), ("active", RAISED_HOVER)],
          lightcolor=[("disabled", BG), ("pressed", LINE), ("active", RAISED_HOVER)],
          darkcolor=[("disabled", BG), ("pressed", LINE), ("active", RAISED_HOVER)],
          foreground=[("disabled", MUTED)],
          bordercolor=[("focus", ACCENT), ("disabled", LINE)])
    s.configure("Primary.TButton", background=ACCENT, foreground=ON_ACCENT, font=STRONG,
                bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=ON_ACCENT)
    s.map("Primary.TButton",
          background=[("disabled", RAISED), ("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
          lightcolor=[("disabled", RAISED), ("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
          darkcolor=[("disabled", RAISED), ("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
          foreground=[("disabled", MUTED)],
          bordercolor=[("focus", TEXT), ("disabled", RAISED)])

    s.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=FIELD,
                indicatorforeground=ACCENT, indicatormargin=(0, 0, 8, 0), focuscolor=ACCENT,
                padding=(0, 2))
    s.map("TCheckbutton", background=[("active", BG)],
          indicatorbackground=[("pressed", RAISED), ("selected", FIELD)],
          foreground=[("disabled", MUTED)])

    # Progress: a thin amber line
    s.configure("Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT, thickness=4,
                bordercolor=FIELD, lightcolor=ACCENT, darkcolor=ACCENT)

    # Table
    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                rowheight=28, font=MONO, borderwidth=0, bordercolor=PANEL)
    s.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background=BG, foreground=MUTED, font=SMALL, relief="flat",
                padding=(8, 7), bordercolor=LINE, lightcolor=BG, darkcolor=BG)
    s.map("Treeview.Heading", background=[("active", RAISED)], foreground=[("active", TEXT)])
    s.configure("Vertical.TScrollbar", background=RAISED, troughcolor=PANEL, bordercolor=PANEL,
                arrowcolor=MUTED, lightcolor=RAISED, darkcolor=RAISED, gripcount=0)
    s.map("Vertical.TScrollbar", background=[("active", RAISED_HOVER)])

    s.configure("TPanedwindow", background=BG)
    s.configure("Sash", sashthickness=10, gripcount=0, background=BG, lightcolor=BG, bordercolor=BG)


def menu(root: tk.Misc) -> tk.Menu:
    return tk.Menu(root, tearoff=False, background=PANEL, foreground=TEXT, borderwidth=0,
                   activebackground=SELECT, activeforeground=TEXT,
                   disabledforeground=mix(MUTED, PANEL, 0.4), font=BODY)
