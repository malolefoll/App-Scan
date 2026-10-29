"""TCP port probing and common port definitions."""

from __future__ import annotations

import socket
import time

# Ports checked by default. Keep this list short: it is probed on every host.
COMMON_PORTS: dict[int, str] = {
    21: "ftp",
    22: "ssh",
    23: "telnet",
    53: "dns",
    80: "http",
    139: "netbios",
    443: "https",
    445: "smb",
    3389: "rdp",
    8006: "proxmox",
    8080: "http-alt",
    9100: "printer",
}


# Clear-text logins and Windows sharing: worth a second look when open.
SENSITIVE_PORTS = {21, 23, 139, 445, 3389}


def service_name(port: int) -> str:
    """Return a human readable service name for a port, or '?' if unknown."""
    return COMMON_PORTS.get(port, "?")


def parse_ports(spec: str) -> list[int]:
    """Parse a port specification such as "22,80,8000-8005" into a sorted list.

    Raises ValueError on invalid input.
    """
    ports: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_s, end_s = chunk.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                raise ValueError(f"invalid port range: {chunk}")
            ports.update(range(start, end + 1))
        else:
            ports.add(int(chunk))
    for p in ports:
        if not 1 <= p <= 65535:
            raise ValueError(f"port out of range: {p}")
    return sorted(ports)


def probe_port(ip: str, port: int, timeout: float = 0.5) -> float | None:
    """Try a TCP connection. Return latency in ms if the port is open, else None."""
    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return (time.perf_counter() - start) * 1000
    except ConnectionRefusedError:
        # The host answered (RST): it is alive even though the port is closed.
        return -1.0
    except OSError:
        return None
