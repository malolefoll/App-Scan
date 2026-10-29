"""Animated 3D view of the scanned devices, drawn on a plain Tkinter Canvas.

No OpenGL and no dependency: every frame, points are rotated around the
camera and projected with a simple perspective (screen = focal / depth).
Devices are boxes shaped and coloured by guessed kind, linked to a central
"scanner" hub, with packets flowing on the links and a radar sweep while a
scan is running.
"""

from __future__ import annotations

import ipaddress
import math
import time
import tkinter as tk
from collections.abc import Callable

from ..i18n import Translator
from ..models import Host
from ..ports import SENSITIVE_PORTS, service_name
from . import theme

BG = theme.FIELD
GRID = theme.GRID
ACCENT = theme.ACCENT
TEXT = theme.TEXT
MUTED = theme.MUTED
DANGER = theme.DANGER
FRAME_MS = 33
FLOOR_Y = -0.75
LIGHT = (-0.35, 0.75, -0.56)  # towards the viewer, from above left

# kind -> (colour, half size of the box: width, height, depth)
KINDS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "router": (theme.KIND_COLORS["router"], (0.42, 0.11, 0.28)),
    "server": (theme.KIND_COLORS["server"], (0.20, 0.42, 0.28)),
    "pc": (theme.KIND_COLORS["pc"], (0.32, 0.21, 0.06)),
    "printer": (theme.KIND_COLORS["printer"], (0.30, 0.15, 0.24)),
    "device": (theme.KIND_COLORS["device"], (0.18, 0.18, 0.18)),
}
# Box faces: corner indices (index = x*4 + y*2 + z, with 1 = positive side) and normal.
FACES = [
    ((4, 5, 7, 6), (1, 0, 0)), ((0, 2, 3, 1), (-1, 0, 0)),
    ((2, 6, 7, 3), (0, 1, 0)), ((0, 1, 5, 4), (0, -1, 0)),
    ((1, 3, 7, 5), (0, 0, 1)), ((0, 4, 6, 2), (0, 0, -1)),
]


def classify(host: Host, gateway: str | None) -> str:
    """Guess what a device is from its open ports (good enough for a picture)."""
    ports = set(host.open_ports)
    if host.ip == gateway:
        return "router"
    if 9100 in ports:
        return "printer"
    if 3389 in ports:
        return "pc"
    if ports & {22, 8006}:  # SSH or Proxmox: a server (a NAS sharing with SMB too)
        return "server"
    if ports & {139, 445}:
        return "pc"
    return "device"


def guess_gateway(hosts: list[Host]) -> str | None:
    """The router is usually .1 or .254, and often answers DNS (53)."""
    ips = {h.ip for h in hosts}
    for h in hosts:
        if 53 in h.open_ports:
            return h.ip
    for suffix in (".1", ".254"):
        for ip in sorted(ips):
            if ip.endswith(suffix):
                return ip
    return None


_mix = theme.mix


def _ease_out_back(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2


class _Node:
    __slots__ = ("host", "kind", "pos", "target", "born", "spin", "phase")

    def __init__(self, host: Host, kind: str, born: float, index: int):
        self.host = host
        self.kind = kind
        self.pos = [0.0, 0.0, 0.0]  # appears at the hub, then flies to its place
        self.target = [0.0, 0.0, 0.0]
        self.born = born
        self.spin = index * 0.7
        self.phase = (index * 0.137) % 1


class NetworkView3D(tk.Canvas):
    def __init__(self, master, t: Translator, on_select: Callable[[str], None] | None = None,
                 on_activate: Callable[[str], None] | None = None, **kw):
        super().__init__(master, background=BG, highlightthickness=0, **kw)
        self.t = t
        self.on_select, self.on_activate = on_select, on_activate
        self.nodes: dict[str, _Node] = {}
        self.gateway: str | None = None
        self.visible: set[str] | None = None
        self.selected: str | None = None
        self.hovered: str | None = None
        self.scanning = False
        self.progress = 0.0
        self.t0 = time.perf_counter()
        self.yaw, self.pitch, self.yaw_vel = 0.6, 0.34, 0.0
        self.zoom = 1.0
        self.dist = 8.0
        self.radius = 3.0
        self.ripples: list[tuple[float, float, float, str]] = []  # x, z, start, colour
        self._hits: list[tuple[str, float, float, float]] = []
        self._drag: tuple[int, int] | None = None
        self._dragged = False
        self._width = self._height = 1  # not _w: Tkinter uses it for the widget path
        # Windows "Show animations" off: the scene stays still, only data changes it.
        self.still = theme.reduced_motion()

        self.bind("<Configure>", lambda e: self._resize(e.width, e.height))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion_drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda e: setattr(self, "hovered", None))
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._zoom_by(0.9))  # Linux wheel
        self.bind("<Button-5>", lambda e: self._zoom_by(1.1))
        self.after(FRAME_MS, self._tick)

    # -- data from the app ------------------------------------------------------
    def clear(self) -> None:
        self.nodes.clear()
        self.ripples.clear()
        self.selected = self.hovered = None
        self._relayout()

    def add_host(self, host: Host) -> None:
        now = self._now()
        node = self.nodes.get(host.ip)
        if node is None:
            node = _Node(host, "device", now, len(self.nodes))
            self.nodes[host.ip] = node
        node.host = host
        self._relayout()
        self.ripples.append((node.target[0], node.target[2], now, KINDS[node.kind][0]))

    def set_hosts(self, hosts: list[Host]) -> None:
        """Replace the data (end of scan: same hosts, now with MAC and vendor)."""
        keep = {h.ip for h in hosts}
        for ip in list(self.nodes):
            if ip not in keep:
                del self.nodes[ip]
        for h in hosts:
            if h.ip in self.nodes:
                self.nodes[h.ip].host = h
            else:
                self.add_host(h)
        self._relayout()

    def set_scanning(self, running: bool) -> None:
        self.scanning = running
        if running:
            self.progress = 0.0

    def set_visible(self, ips: set[str] | None) -> None:
        self.visible = ips

    def select(self, ip: str | None) -> None:
        self.selected = ip

    # -- layout -------------------------------------------------------------------
    def _relayout(self) -> None:
        hosts = [n.host for n in self.nodes.values()]
        self.gateway = guess_gateway(hosts)
        ordered = sorted(self.nodes.values(), key=lambda n: ipaddress.IPv4Address(n.host.ip))
        others = []
        for n in ordered:
            n.kind = classify(n.host, self.gateway)
            if n.host.ip == self.gateway:
                n.target = [0.0, 1.35, 0.0]  # the router floats above the scanner
            else:
                others.append(n)
        per_ring = 14
        ring = 0
        for i, n in enumerate(others):
            ring = i // per_ring
            in_ring = min(per_ring, len(others) - ring * per_ring)
            a = 2 * math.pi * (i % per_ring) / in_ring + ring * 0.4
            r = 2.4 + ring * 1.2
            y = 0.25 if n.kind == "server" else 0.0
            n.target = [math.cos(a) * r, y, math.sin(a) * r]
        self.radius = 2.4 + ring * 1.2 if others else 2.4

    # -- maths ----------------------------------------------------------------------
    def _now(self) -> float:
        return time.perf_counter() - self.t0

    def _resize(self, w: int, h: int) -> None:
        self._width, self._height = max(1, w), max(1, h)

    def _rot(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        cy, sy, cp, sp = self._cy, self._sy, self._cp, self._sp
        x1 = x * cy - z * sy
        z1 = x * sy + z * cy
        return x1, y * cp - z1 * sp, y * sp + z1 * cp

    def _project(self, x: float, y: float, z: float) -> tuple[float, float, float, float]:
        x1, y1, z1 = self._rot(x, y, z)
        d = max(0.3, self.dist + z1)
        s = self.focal / d
        return self.cx + x1 * s, self.cy - y1 * s, z1, s

    def _fog(self, depth: float) -> float:
        """0 for the closest objects, up to 0.6 for the farthest."""
        return max(0.0, min(0.6, (depth + self.radius) / (2 * self.radius + 0.01) * 0.6))

    # -- frame ----------------------------------------------------------------------
    def _tick(self) -> None:
        try:
            if self.winfo_ismapped():
                self._frame()
        finally:
            self.after(FRAME_MS, self._tick)

    def _frame(self) -> None:
        t = 0.0 if self.still else self._now()
        if self._drag is None:
            self.yaw_vel *= 0.94
            self.yaw += self.yaw_vel + (0.0 if self.hovered or self.still else 0.0035)
        self._cy, self._sy = math.cos(self.yaw), math.sin(self.yaw)
        self._cp, self._sp = math.cos(self.pitch), math.sin(self.pitch)
        w, h = self._width, self._height
        self.cx, self.cy = w / 2, h / 2 + h * 0.08
        self.focal = min(w * 0.85, h * 2.6)
        want = (4.2 + self.radius * 1.9) * self.zoom
        self.dist += (want - self.dist) * 0.08

        for n in self.nodes.values():  # glide towards the target position
            for i in range(3):
                n.pos[i] += (n.target[i] - n.pos[i]) * (1.0 if self.still else 0.09)

        self.delete("all")
        self._hits = []
        self._draw_floor(t)
        hub = self._draw_hub(t)
        self._draw_links(t, hub)
        self._draw_nodes(t)
        self._draw_hud()

    def _floor_circle(self, x: float, z: float, r: float, color: str, width: float = 1,
                      steps: int = 56) -> None:
        pts = []
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            sx, sy, _, _ = self._project(x + math.cos(a) * r, FLOOR_Y, z + math.sin(a) * r)
            pts += (sx, sy)
        self.create_line(*pts, fill=color, width=width, smooth=True)

    def _draw_floor(self, t: float) -> None:
        rmax = self.radius + 1.2
        r = 1.2
        while r <= rmax + 0.01:
            self._floor_circle(0, 0, r, GRID)
            r += 1.2
        for k in range(12):
            a = k * math.pi / 6
            x0, y0, _, _ = self._project(math.cos(a) * 0.6, FLOOR_Y, math.sin(a) * 0.6)
            x1, y1, _, _ = self._project(math.cos(a) * rmax, FLOOR_Y, math.sin(a) * rmax)
            self.create_line(x0, y0, x1, y1, fill=_mix(BG, GRID, 0.7))

        if self.scanning:
            # radar sweep: a bright line followed by a fading trail
            base = t * 2.4
            for k in range(14, -1, -1):
                a = base - k * 0.045
                x0, y0, _, _ = self._project(0, FLOOR_Y, 0)
                x1, y1, _, _ = self._project(math.cos(a) * rmax, FLOOR_Y, math.sin(a) * rmax)
                self.create_line(x0, y0, x1, y1, fill=_mix(BG, ACCENT, (1 - k / 15) ** 2),
                                 width=2 if k == 0 else 1)
            # waves leaving the scanner
            for k in range(2):
                p = ((t / 1.8) + k / 2) % 1
                self._floor_circle(0, 0, 0.4 + p * rmax, _mix(ACCENT, BG, p), width=1.5)

        # ripple where a device has just been found
        alive = []
        for x, z, start, color in self.ripples:
            p = (t - start) / 1.4
            if 0 <= p < 1:
                self._floor_circle(x, z, 0.25 + p * 1.1, _mix(color, BG, p), width=2, steps=32)
                alive.append((x, z, start, color))
        self.ripples = alive

    def _draw_hub(self, t: float) -> tuple[float, float]:
        """The scanner itself: a spinning diamond in the middle."""
        sx, sy, _, s = self._project(0, 0, 0)
        r = 0.32 * s
        a = t * 1.4
        pts = []
        for k in range(4):
            ang = a + k * math.pi / 2
            px, py, _, _ = self._project(math.cos(ang) * 0.32, 0, math.sin(ang) * 0.32)
            pts.append((px, py))
        top = self._project(0, 0.42, 0)[:2]
        bottom = self._project(0, -0.42, 0)[:2]
        for i in range(4):
            p1, p2 = pts[i], pts[(i + 1) % 4]
            shade = 0.45 + 0.4 * math.sin(a + i)
            # the scanner is bare metal: amber stays the colour of the uplink and the sweep
            self.create_polygon(*top, *p1, *p2, fill=_mix(BG, TEXT, shade * 0.8), outline=TEXT)
            self.create_polygon(*bottom, *p1, *p2, fill=_mix(BG, TEXT, shade * 0.45), outline=TEXT)
        pulse = 1 + 0.15 * math.sin(t * 3)
        self.create_oval(sx - r * 1.6 * pulse, sy - r * 0.8 * pulse, sx + r * 1.6 * pulse,
                         sy + r * 0.8 * pulse, outline=_mix(BG, TEXT, 0.35))
        self.create_text(sx, sy + r * 1.9, text="NetInv", fill=TEXT, font=theme.SMALL)
        return sx, sy

    def _shown(self, ip: str) -> bool:
        return self.visible is None or ip in self.visible

    def _draw_links(self, t: float, hub: tuple[float, float]) -> None:
        speed = 0.55 if self.scanning else 0.28
        for n in self.nodes.values():
            x, y, z = n.pos
            nx, ny, depth, s = self._project(x, y, z)
            color = KINDS[n.kind][0]
            fog = self._fog(depth) + (0.0 if self._shown(n.host.ip) else 0.3)
            self.create_line(*hub, nx, ny, fill=_mix(BG, color, 0.35 - fog * 0.3))
            if not self._shown(n.host.ip):
                continue
            u = (t * speed + n.phase) % 1  # a packet travelling to the device
            px, py = hub[0] + (nx - hub[0]) * u, hub[1] + (ny - hub[1]) * u
            r = max(1.5, 0.045 * s)
            self.create_oval(px - r, py - r, px + r, py + r, fill=_mix(color, BG, fog), outline="")

    def _draw_nodes(self, t: float) -> None:
        drawn = []
        for n in self.nodes.values():
            x, y, z = n.pos
            _, _, depth, _ = self._project(x, y, z)
            drawn.append((depth, n))
        drawn.sort(key=lambda d: -d[0])  # far first, so near boxes are painted on top
        many = len(drawn) > 60
        for depth, n in drawn:
            self._draw_node(n, depth, t, show_label=not many)

    def _draw_node(self, n: _Node, depth: float, t: float, show_label: bool) -> None:
        ip = n.host.ip
        shown = self._shown(ip)
        color, (hw, hh, hd) = KINDS[n.kind]
        grow = 1.0 if self.still else _ease_out_back((t - n.born) / 0.7)
        if grow <= 0.01:
            return
        hw, hh, hd = hw * grow, hh * grow, hd * grow
        x, y, z = n.pos
        y += math.sin(t * 1.3 + n.phase * 6) * 0.05  # gentle float
        fog = self._fog(depth) + (0.0 if shown else 0.35)
        focus = ip in (self.selected, self.hovered)

        # corners of the box, turning slowly on itself
        spin = n.spin + t * 0.25
        cs, sn = math.cos(spin), math.sin(spin)
        corners = []
        for i in range(8):
            lx = hw if i & 4 else -hw
            ly = hh if i & 2 else -hh
            lz = hd if i & 1 else -hd
            corners.append((x + lx * cs - lz * sn, y + ly, z + lx * sn + lz * cs))
        cam = [self._rot(*c) for c in corners]
        proj = [self._project(*c) for c in corners]
        lx, ly, lz = LIGHT
        edge = _mix(_mix(color, "#ffffff", 0.45 if focus else 0.15), BG, fog)
        for idx, (nx0, ny0, nz0) in FACES:
            # rotate the normal like the box, then like the camera
            nxr, nzr = nx0 * cs - nz0 * sn, nx0 * sn + nz0 * cs
            ncx, ncy, ncz = self._rot(nxr, ny0, nzr)
            fx = sum(cam[i][0] for i in idx) / 4
            fy = sum(cam[i][1] for i in idx) / 4
            fz = sum(cam[i][2] for i in idx) / 4
            if ncx * -fx + ncy * -fy + ncz * (-self.dist - fz) <= 0:
                continue  # face turned away from the camera
            light = max(0.0, ncx * lx + ncy * ly + ncz * lz)
            fill = _mix(_mix(BG, color, 0.28 + 0.62 * light), BG, fog)
            pts = [c for i in idx for c in proj[i][:2]]
            self.create_polygon(*pts, fill=fill, outline=edge, width=2 if focus else 1)

        sx, sy, _, s = self._project(x, y, z)
        size = max(hw, hh) * s * 1.25 + 4
        self._hits.append((ip, sx, sy, size))

        if shown and SENSITIVE_PORTS & set(n.host.open_ports):
            p = (t * 0.9 + n.phase) % 1  # warning pulse
            rr = size * (0.7 + p * 0.6)
            self.create_oval(sx - rr, sy - rr * 0.6, sx + rr, sy + rr * 0.6,
                             outline=_mix(DANGER, BG, p), width=2)
        if focus:
            rr = size * 1.1
            self.create_oval(sx - rr, sy - rr * 0.65, sx + rr, sy + rr * 0.65, outline=TEXT, width=2)
        # Labels only on the front half of the scene, so they do not pile up.
        if shown and (focus or (show_label and depth < self.radius * 0.25)):
            fs = max(7, min(10, round(0.08 * s)))
            name = n.host.hostname.split(".")[0][:18] if n.host.hostname else ip
            self.create_text(sx, sy + size * 0.8 + 2, text=name, anchor="n",
                             fill=_mix(TEXT, BG, fog + 0.05), font=(theme.BODY[0], fs))
            if name != ip:
                self.create_text(sx, sy + size * 0.8 + fs + 7, text=ip, anchor="n",
                                 fill=_mix(MUTED, BG, fog), font=(theme.MONO[0], max(7, fs - 1)))

    def _draw_hud(self) -> None:
        t = self.t
        w, h = self._width, self._height
        pad = 18
        self.create_text(pad, pad, anchor="nw", text=t("view_title"), fill=TEXT, font=theme.STRONG)
        if self.scanning:
            pct = round(self.progress * 100)
            self.create_text(pad, pad + 24, anchor="nw", text=t("view_scanning", pct=pct),
                             fill=ACCENT, font=theme.SMALL)
        elif not self.nodes:
            self.create_text(w / 2, h * 0.22, text=t("view_empty"), fill=MUTED, font=theme.BODY)

        # legend: one cable colour per kind, with its count
        counts: dict[str, int] = {}
        for n in self.nodes.values():
            counts[n.kind] = counts.get(n.kind, 0) + 1
        y = h - pad
        for kind in reversed(list(KINDS)):
            color = KINDS[kind][0] if counts.get(kind) else _mix(KINDS[kind][0], BG, 0.6)
            self.create_rectangle(pad, y - 3, pad + 14, y, fill=color, outline="")  # cable stub
            self.create_text(pad + 22, y - 2, anchor="w", fill=TEXT if counts.get(kind) else MUTED,
                             text=t("kind_" + kind), font=theme.SMALL)
            self.create_text(pad + 172, y - 2, anchor="e", fill=TEXT if counts.get(kind) else MUTED,
                             text=str(counts.get(kind, 0)), font=theme.MONO)
            y -= 20
        self.create_text(w - pad, h - pad + 4, anchor="se", text=t("view_hint"), fill=MUTED,
                         font=theme.SMALL)

        # details of the device under the mouse (or selected): label left, value right
        node = self.nodes.get(self.hovered or "") or self.nodes.get(self.selected or "")
        if node:
            hst = node.host
            dash = t("unknown")
            color = KINDS[node.kind][0]
            rows = [
                (t("col_ip"), hst.ip),
                (t("col_mac"), hst.mac or dash),
                (t("col_vendor"), hst.vendor or dash),
                (t("col_ports"), ", ".join(f"{p}/{service_name(p)}" for p in hst.open_ports) or dash),
                (t("col_latency"), f"{hst.latency_ms:.1f}" if hst.latency_ms is not None else dash),
            ]
            bw = 320
            bx, by = w - bw - pad, pad
            card = self.create_rectangle(bx, by, bx + bw, by + 1, fill=theme.PANEL, outline=theme.LINE)
            bar = self.create_rectangle(bx, by, bx + 3, by + 1, fill=color, outline="")
            self.create_text(bx + 16, by + 12, anchor="nw", text=hst.hostname or hst.ip,
                             fill=TEXT, font=theme.STRONG, width=bw - 28)
            self.create_text(bx + 16, by + 34, anchor="nw", text=t("kind_" + node.kind),
                             fill=color, font=theme.SMALL)
            yy = by + 60
            for label, value in rows:
                self.create_text(bx + 16, yy, anchor="nw", text=label, fill=MUTED, font=theme.SMALL)
                item = self.create_text(bx + bw - 14, yy, anchor="ne", text=value, fill=TEXT,
                                        font=theme.MONO, width=bw - 140, justify="right")
                yy = self.bbox(item)[3] + 6  # long values wrap: the next row starts below
            self.coords(card, bx, by, bx + bw, yy + 8)
            self.coords(bar, bx, by, bx + 3, yy + 8)

    # -- mouse ------------------------------------------------------------------------
    def _hit(self, x: float, y: float) -> str | None:
        best, best_d = None, 1e9
        for ip, sx, sy, r in self._hits:
            d = math.hypot(x - sx, y - sy)
            if d <= r + 6 and d < best_d and self._shown(ip):
                best, best_d = ip, d
        return best

    def _press(self, e) -> None:
        self._drag = (e.x, e.y)
        self._dragged = False

    def _motion_drag(self, e) -> None:
        if self._drag is None:
            return
        dx, dy = e.x - self._drag[0], e.y - self._drag[1]
        if abs(dx) + abs(dy) > 2:
            self._dragged = True
        self.yaw_vel = -dx * 0.008
        self.yaw += self.yaw_vel
        self.pitch = max(0.05, min(1.25, self.pitch + dy * 0.006))
        self._drag = (e.x, e.y)

    def _release(self, e) -> None:
        self._drag = None
        if not self._dragged:
            ip = self._hit(e.x, e.y)
            self.selected = ip
            if ip and self.on_select:
                self.on_select(ip)

    def _double(self, e) -> None:
        ip = self._hit(e.x, e.y)
        if ip and self.on_activate:
            self.on_activate(ip)

    def _hover(self, e) -> None:
        if self._drag is None:
            self.hovered = self._hit(e.x, e.y)
            self.configure(cursor="hand2" if self.hovered else "fleur")

    def _wheel(self, e) -> None:
        self._zoom_by(0.9 if e.delta > 0 else 1.1)

    def _zoom_by(self, k: float) -> None:
        self.zoom = max(0.55, min(2.2, self.zoom * k))
