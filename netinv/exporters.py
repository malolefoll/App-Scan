"""Turn scan results into text: terminal table, CSV, JSON, HTML.

To add a format, write a function `to_<name>(hosts, t) -> str` and register it
in EXPORTERS below.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
from collections.abc import Callable

from . import __version__
from .i18n import Translator
from .models import HOST_FIELDS, Host
from .ports import service_name


def _ports_str(host: Host, with_names: bool = True) -> str:
    if with_names:
        return ", ".join(f"{p}/{service_name(p)}" for p in host.open_ports)
    return " ".join(str(p) for p in host.open_ports)


def _row(host: Host, t: Translator) -> list[str]:
    dash = t("unknown")
    return [
        host.ip,
        host.hostname or dash,
        host.mac or dash,
        host.vendor or dash,
        _ports_str(host) or dash,
        f"{host.latency_ms:.1f}" if host.latency_ms is not None else dash,
    ]


def _headers(t: Translator) -> list[str]:
    return [
        t(k)
        for k in ("col_ip", "col_hostname", "col_mac", "col_vendor", "col_ports", "col_latency")
    ]


def to_table(hosts: list[Host], t: Translator) -> str:
    """Plain text table for the terminal."""
    rows = [_headers(t)] + [_row(h, t) for h in hosts]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for n, r in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def to_csv(hosts: list[Host], t: Translator) -> str:
    buf = io.StringIO()
    # "\n" only: write_text() already turns it into "\r\n" on Windows (else blank lines in Excel)
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HOST_FIELDS)
    for h in hosts:
        d = h.to_dict()
        d["open_ports"] = _ports_str(h, with_names=False)
        writer.writerow(["" if d[f] is None else d[f] for f in HOST_FIELDS])
    return buf.getvalue()


def to_json(hosts: list[Host], t: Translator) -> str:
    payload = {
        "generator": f"netinv {__version__}",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "hosts": [h.to_dict() for h in hosts],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


_HTML_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e2dd; --accent:#0b6e4f; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141413; --fg:#ececea; --muted:#9a9a94; --line:#2c2c2a; --accent:#4cc38a; }}
}}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
       font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
p.meta {{ color:var(--muted); margin:0 0 20px; }}
input {{ width:100%; max-width:360px; padding:8px 10px; border:1px solid var(--line);
        border-radius:6px; background:transparent; color:inherit; font:inherit; }}
.wrap {{ overflow-x:auto; margin-top:16px; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
          white-space:nowrap; }}
th {{ font-size:13px; color:var(--muted); font-weight:600; }}
td.mono {{ font-family:ui-monospace, Menlo, Consolas, monospace; font-size:13px; }}
.count {{ color:var(--accent); font-weight:600; }}
</style>
</head>
<body>
<main>
<h1>{title} <span class="count">({count})</span></h1>
<p class="meta">{generated}</p>
<input id="q" type="search" placeholder="{search}" aria-label="{search}">
<div class="wrap"><table>
<thead><tr>{head}</tr></thead>
<tbody id="rows">
{body}
</tbody></table></div>
</main>
<script>
document.getElementById('q').addEventListener('input', function (e) {{
  var q = e.target.value.toLowerCase();
  document.querySelectorAll('#rows tr').forEach(function (tr) {{
    tr.style.display = tr.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
  }});
}});
</script>
</body>
</html>
"""


def to_html(hosts: list[Host], t: Translator) -> str:
    """A single self-contained HTML page, with a search box. No external resources."""
    esc = html.escape
    mono = {0, 2}  # IP and MAC columns
    head = "".join(f"<th>{esc(h)}</th>" for h in _headers(t))
    body = "\n".join(
        "<tr>"
        + "".join(
            f'<td class="mono">{esc(c)}</td>' if i in mono else f"<td>{esc(c)}</td>"
            for i, c in enumerate(_row(h, t))
        )
        + "</tr>"
        for h in hosts
    )
    return _HTML_TEMPLATE.format(
        lang=esc(t.lang),
        title=esc(t("report_title")),
        count=len(hosts),
        generated=esc(
            t(
                "report_generated",
                date=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                version=__version__,
            )
        ),
        search=esc(t("report_search")),
        head=head,
        body=body,
    )


EXPORTERS: dict[str, Callable[[list[Host], Translator], str]] = {
    "table": to_table,
    "csv": to_csv,
    "json": to_json,
    "html": to_html,
}


def format_from_path(path: str) -> str | None:
    """Guess the export format from a file extension (report.csv -> 'csv')."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {"csv": "csv", "json": "json", "html": "html", "htm": "html", "txt": "table"}.get(ext)
