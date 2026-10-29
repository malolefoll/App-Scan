"""Look up the manufacturer of a device from its MAC address (OUI prefix).

netinv ships a small built-in list in data/oui.txt. Anyone can extend it:
one line per prefix, format "AA:BB:CC<TAB>Vendor name".
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources


def _parse_oui_lines(lines) -> dict[str, str]:
    table: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        prefix, _, name = line.partition("\t")
        if prefix and name:
            table[prefix.strip().upper().replace("-", ":")] = name.strip()
    return table


@lru_cache(maxsize=1)
def load_oui_table() -> dict[str, str]:
    text = resources.files("netinv").joinpath("data/oui.txt").read_text(encoding="utf-8")
    return _parse_oui_lines(text.splitlines())


def lookup_vendor(mac: str | None, table: dict[str, str] | None = None) -> str | None:
    """Return the vendor for a MAC address, or None if unknown."""
    if not mac:
        return None
    table = table if table is not None else load_oui_table()
    prefix = mac.upper().replace("-", ":")[:8]
    known = table.get(prefix)
    if known:
        return known
    if is_locally_administered(mac):
        return "(random / private MAC)"
    return None


def is_locally_administered(mac: str) -> bool:
    """True for randomized MACs (phones with privacy mode, VMs, containers)."""
    try:
        first_octet = int(mac.replace("-", ":").split(":")[0], 16)
    except ValueError:
        return False
    return bool(first_octet & 0b10)
