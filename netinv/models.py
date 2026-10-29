"""Data models shared across netinv."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Host:
    """A device discovered on the network."""

    ip: str
    alive: bool = False
    hostname: str | None = None
    mac: str | None = None
    vendor: str | None = None
    open_ports: list[int] = field(default_factory=list)
    latency_ms: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# Field order used by every exporter, so columns are always consistent.
HOST_FIELDS = ["ip", "alive", "hostname", "mac", "vendor", "open_ports", "latency_ms"]
