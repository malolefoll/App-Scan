"""Host discovery and scanning logic."""

from __future__ import annotations

import ipaddress
import platform
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .arp import read_arp_table
from .models import Host
from .ports import COMMON_PORTS, probe_port
from .vendor import lookup_vendor

MAX_HOSTS_DEFAULT = 4096

# Windows: without this, each `ping` opens a console window when the app runs
# without a console (pythonw). The flag does not exist elsewhere: 0 = no effect.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Ports used only to decide whether a host is up (any answer, even "refused", counts).
DISCOVERY_PORTS = [80, 443, 22, 445, 139, 3389]


def expand_targets(spec: str, max_hosts: int = MAX_HOSTS_DEFAULT) -> list[str]:
    """Turn a target spec into a list of IPv4 addresses.

    Accepted forms (comma separated): "192.168.1.0/24", "192.168.1.42",
    "192.168.1.10-20" (last octet range).
    """
    ips: list[str] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if "/" in part:
            net = ipaddress.ip_network(part, strict=False)
            if net.version != 4:
                raise ValueError("only IPv4 is supported for now")
            hosts = list(net.hosts()) or [net.network_address]
            ips.extend(str(h) for h in hosts)
        elif "-" in part:
            base, end_s = part.rsplit("-", 1)
            start_ip = ipaddress.IPv4Address(base)
            prefix, start_octet = str(start_ip).rsplit(".", 1)
            end_octet = int(end_s)
            if not int(start_octet) <= end_octet <= 255:
                raise ValueError(f"invalid range: {part}")
            ips.extend(f"{prefix}.{o}" for o in range(int(start_octet), end_octet + 1))
        else:
            ips.append(str(ipaddress.IPv4Address(part)))
        if len(ips) > max_hosts:
            raise ValueError(
                f"target expands to more than {max_hosts} hosts; use --max-hosts to allow it"
            )
    # Remove duplicates, keep order.
    return list(dict.fromkeys(ips))


def guess_local_network() -> str:
    """Guess the local /24 network from the machine's primary IPv4 address.

    Uses a UDP socket "connect", which sends no packet.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed for real
            ip = s.getsockname()[0]
        except OSError:
            ip = "127.0.0.1"
    return str(ipaddress.ip_network(f"{ip}/24", strict=False))


def system_ping(ip: str, timeout: float = 1.0) -> float | None:
    """Ping using the system `ping` command. Return latency in ms or None."""
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), ip]
    start = time.perf_counter()
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout + 2, check=False,
                             creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    # Windows returns 0 even for "Destination host unreachable" replies sent by
    # the local machine. A real echo reply always contains "TTL=" (in every language).
    if b"TTL=" not in res.stdout.upper():
        return None
    return (time.perf_counter() - start) * 1000


def reverse_dns(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return None


def check_host(
    ip: str,
    ports: Iterable[int],
    timeout: float = 0.5,
    use_ping: bool = True,
    resolve: bool = True,
) -> Host:
    """Scan one IP: is it up, which of `ports` are open, what is its name."""
    host = Host(ip=ip)
    ports = list(ports)

    latency = system_ping(ip, timeout=max(timeout, 1.0)) if use_ping else None
    if latency is not None:
        host.alive, host.latency_ms = True, round(latency, 1)

    for port in sorted(set(ports) | set(DISCOVERY_PORTS)):
        result = probe_port(ip, port, timeout=timeout)
        if result is None:
            continue
        host.alive = True
        if result >= 0:
            if port in ports:
                host.open_ports.append(port)
            if host.latency_ms is None:
                host.latency_ms = round(result, 1)

    if host.alive and resolve:
        host.hostname = reverse_dns(ip)
    return host


def scan(
    targets: list[str],
    ports: Iterable[int] | None = None,
    timeout: float = 0.5,
    workers: int = 64,
    use_ping: bool = True,
    resolve: bool = True,
    include_down: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
    on_host: Callable[[Host], None] | None = None,
    stop: threading.Event | None = None,
) -> list[Host]:
    """Scan every target in parallel and return the discovered hosts, sorted by IP.

    `on_host` is called as soon as a host answers (before MAC lookup), and setting
    `stop` ends the scan early with the hosts found so far.
    """
    ports = list(ports) if ports is not None else list(COMMON_PORTS)
    total = len(targets)
    done = 0
    results: list[Host] = []

    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures = [pool.submit(check_host, ip, ports, timeout, use_ping, resolve) for ip in targets]
        for fut in as_completed(futures):
            host = fut.result()
            results.append(host)
            done += 1
            if on_progress:
                on_progress(done, total)
            if on_host and host.alive:
                on_host(host)
            if stop is not None and stop.is_set():
                break
    finally:
        # On stop, drop the queued addresses instead of waiting for them.
        pool.shutdown(wait=True, cancel_futures=True)

    # Probing filled the OS ARP cache: use it to add MAC addresses and vendors,
    # and to catch devices that answered ARP but blocked ping and TCP.
    arp = read_arp_table()
    for host in results:
        mac = arp.get(host.ip)
        if mac:
            host.alive = True
            host.mac = mac
            host.vendor = lookup_vendor(mac)

    if not include_down:
        results = [h for h in results if h.alive]
    results.sort(key=lambda h: ipaddress.IPv4Address(h.ip))
    return results
