"""Command line interface: `netinv scan ...`."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .exporters import EXPORTERS, format_from_path
from .i18n import Translator, available_languages
from .ports import COMMON_PORTS, parse_ports
from .scanner import MAX_HOSTS_DEFAULT, expand_targets, guess_local_network, scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netinv",
        description="Discover the devices on your local network and export an inventory.",
    )
    parser.add_argument("--version", action="version", version=f"netinv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="scan a network and list the devices found")
    s.add_argument(
        "target",
        nargs="?",
        help="CIDR, IP or range, e.g. 192.168.1.0/24, 192.168.1.10-50 (default: your local /24)",
    )
    s.add_argument(
        "-p",
        "--ports",
        help="ports to check, e.g. 22,80,443 or 8000-8010 "
        f"(default: {','.join(map(str, COMMON_PORTS))})",
    )
    s.add_argument("-o", "--output", help="write results to a file (.csv, .json, .html, .txt)")
    s.add_argument(
        "-f",
        "--format",
        choices=sorted(EXPORTERS),
        help="output format (default: from file extension, else table)",
    )
    s.add_argument(
        "-t", "--timeout", type=float, default=0.5, help="TCP timeout in seconds (default: 0.5)"
    )
    s.add_argument("-w", "--workers", type=int, default=64, help="parallel workers (default: 64)")
    s.add_argument("--no-ping", action="store_true", help="do not use the system ping command")
    s.add_argument("--no-dns", action="store_true", help="skip reverse DNS lookups")
    s.add_argument("--all", action="store_true", help="also list addresses that did not answer")
    s.add_argument(
        "--max-hosts",
        type=int,
        default=MAX_HOSTS_DEFAULT,
        help=f"refuse targets larger than this (default: {MAX_HOSTS_DEFAULT})",
    )
    s.add_argument(
        "--lang", choices=available_languages(), help="interface language (default: from system)"
    )
    s.add_argument("-q", "--quiet", action="store_true", help="no progress messages")

    g = sub.add_parser("gui", help="open the desktop application")
    g.add_argument(
        "--lang", choices=available_languages(), help="interface language (default: from system)"
    )
    return parser


def _progress(t: Translator):
    def show(done: int, total: int) -> None:
        sys.stderr.write("\r" + t("progress", done=done, total=total))
        if done == total:
            sys.stderr.write("\n")
        sys.stderr.flush()

    return show


def cmd_scan(args: argparse.Namespace) -> int:
    t = Translator(args.lang)
    say = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))

    target = args.target
    if not target:
        target = guess_local_network()
        say(t("guessed_network", network=target))

    try:
        targets = expand_targets(target, max_hosts=args.max_hosts)
    except ValueError as exc:
        print(t("error_target", error=exc), file=sys.stderr)
        return 2
    try:
        ports = parse_ports(args.ports) if args.ports else list(COMMON_PORTS)
    except ValueError as exc:
        print(t("error_ports", error=exc), file=sys.stderr)
        return 2

    say(t("scanning", count=len(targets), target=target))
    start = time.perf_counter()
    hosts = scan(
        targets,
        ports=ports,
        timeout=args.timeout,
        workers=args.workers,
        use_ping=not args.no_ping,
        resolve=not args.no_dns,
        include_down=args.all,
        on_progress=None if args.quiet else _progress(t),
    )
    elapsed = time.perf_counter() - start

    alive = sum(1 for h in hosts if h.alive)
    if alive:
        say(t("found", count=alive, seconds=f"{elapsed:.1f}"))
    else:
        say(t("none_found"))

    fmt = args.format or (format_from_path(args.output) if args.output else None) or "table"
    text = EXPORTERS[fmt](hosts, t)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        say(t("saved", path=args.output))
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "gui":
        from .ui.app import run  # imported here: the CLI must work even without Tkinter

        return run(args.lang)
    return 1


if __name__ == "__main__":
    sys.exit(main())
