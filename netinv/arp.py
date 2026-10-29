"""Read the operating system's ARP / neighbour table to map IPs to MAC addresses.

No root access is needed: we only read what the OS already knows.
"""

from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

_MAC_RE = re.compile(r"([0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2}")
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def normalize_mac(mac: str) -> str:
    """Return a MAC address as lowercase, colon separated, zero padded."""
    parts = re.split(r"[:-]", mac.strip())
    if len(parts) != 6:
        raise ValueError(f"invalid MAC address: {mac}")
    return ":".join(p.zfill(2).lower() for p in parts)


def parse_proc_net_arp(text: str) -> dict[str, str]:
    """Parse the content of Linux /proc/net/arp."""
    table: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 4 and cols[3] != "00:00:00:00:00:00":
            table[cols[0]] = normalize_mac(cols[3])
    return table


def parse_arp_a(text: str) -> dict[str, str]:
    """Parse the output of `arp -a` (Windows, macOS, BSD and Linux net-tools)."""
    table: dict[str, str] = {}
    for line in text.splitlines():
        ip_m = _IP_RE.search(line)
        mac_m = _MAC_RE.search(line)
        if ip_m and mac_m:
            mac = normalize_mac(mac_m.group(0))
            if mac not in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
                table[ip_m.group(1)] = mac
    return table


def read_arp_table() -> dict[str, str]:
    """Return the current ARP table as {ip: mac}. Empty dict if unavailable."""
    proc = Path("/proc/net/arp")
    if platform.system() == "Linux" and proc.exists():
        try:
            return parse_proc_net_arp(proc.read_text())
        except OSError:
            pass
    try:
        out = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=5, check=False,
            # no console window popping up when the app runs without one (Windows)
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_arp_a(out)
