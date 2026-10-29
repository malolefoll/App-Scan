"""Tests without network access: `python -m unittest` from the App-Scan folder."""

from __future__ import annotations

import csv
import io
import json
import unittest

from netinv.arp import normalize_mac, parse_arp_a, parse_proc_net_arp
from netinv.exporters import EXPORTERS, format_from_path
from netinv.i18n import Translator, available_languages
from netinv.models import Host
from netinv.ports import parse_ports, service_name
from netinv.scanner import expand_targets
from netinv.ui.view3d import classify, guess_gateway

T = Translator("fr")
HOSTS = [
    Host("192.168.1.1", True, "box.lan", "aa:bb:cc:00:00:01", "TP-Link", [53, 80, 443], 1.1),
    Host("192.168.1.30", True, None, None, None, [23], None),
]


class TargetsTest(unittest.TestCase):
    def test_cidr_skips_network_and_broadcast(self):
        ips = expand_targets("192.168.1.0/30")
        self.assertEqual(ips, ["192.168.1.1", "192.168.1.2"])

    def test_range_and_list_without_duplicates(self):
        ips = expand_targets("10.0.0.5-7, 10.0.0.6")
        self.assertEqual(ips, ["10.0.0.5", "10.0.0.6", "10.0.0.7"])

    def test_refuses_huge_or_invalid_targets(self):
        with self.assertRaises(ValueError):
            expand_targets("10.0.0.0/16", max_hosts=4096)
        with self.assertRaises(ValueError):
            expand_targets("pas une ip")
        with self.assertRaises(ValueError):
            expand_targets("10.0.0.9-3")


class PortsTest(unittest.TestCase):
    def test_parse_list_and_range(self):
        self.assertEqual(parse_ports("443, 22,8000-8002"), [22, 443, 8000, 8001, 8002])

    def test_rejects_out_of_range(self):
        for bad in ("0", "70000", "90-80", "abc"):
            with self.assertRaises(ValueError):
                parse_ports(bad)

    def test_service_names(self):
        self.assertEqual(service_name(22), "ssh")
        self.assertEqual(service_name(12345), "?")


class ArpTest(unittest.TestCase):
    def test_windows_arp_output(self):
        text = (
            "Interface : 192.168.1.20 --- 0x5\n"
            "  192.168.1.1           a4-b1-c1-0d-0e-0f     dynamique\n"
            "  192.168.1.255         ff-ff-ff-ff-ff-ff     statique\n"
        )
        self.assertEqual(parse_arp_a(text), {"192.168.1.1": "a4:b1:c1:0d:0e:0f"})

    def test_linux_proc_net_arp(self):
        text = (
            "IP address       HW type     Flags       HW address            Mask     Device\n"
            "192.168.1.1      0x1         0x2         a4:b1:c1:0d:0e:0f     *        eth0\n"
            "192.168.1.9      0x1         0x0         00:00:00:00:00:00     *        eth0\n"
        )
        self.assertEqual(parse_proc_net_arp(text), {"192.168.1.1": "a4:b1:c1:0d:0e:0f"})

    def test_normalize_mac_pads_and_lowercases(self):
        self.assertEqual(normalize_mac("A-B-C-1-2-3"), "0a:0b:0c:01:02:03")


class ExportersTest(unittest.TestCase):
    def test_csv_has_no_blank_lines(self):
        rows = list(csv.reader(io.StringIO(EXPORTERS["csv"](HOSTS, T))))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][5], "53 80 443")

    def test_json_round_trip(self):
        data = json.loads(EXPORTERS["json"](HOSTS, T))
        self.assertEqual([h["ip"] for h in data["hosts"]], ["192.168.1.1", "192.168.1.30"])

    def test_html_escapes_values(self):
        evil = [Host("10.0.0.1", True, "<script>alert(1)</script>")]
        self.assertNotIn("<script>alert", EXPORTERS["html"](evil, T))

    def test_format_from_extension(self):
        self.assertEqual(format_from_path("r.HTM"), "html")
        self.assertEqual(format_from_path("r.txt"), "table")
        self.assertIsNone(format_from_path("rapport"))


class TranslationsTest(unittest.TestCase):
    def test_every_language_has_every_key(self):
        keys = {lang: set(Translator(lang)._messages) for lang in available_languages()}
        reference = keys["en"]
        for lang, lang_keys in keys.items():
            self.assertEqual(lang_keys, reference, f"keys differ in {lang}.json")


class View3DTest(unittest.TestCase):
    def test_gateway_and_kinds(self):
        hosts = HOSTS + [
            Host("192.168.1.20", True, open_ports=[22, 8006]),
            Host("192.168.1.42", True, open_ports=[9100]),
            Host("192.168.1.101", True, open_ports=[139, 445, 3389]),
            Host("192.168.1.10", True, open_ports=[22, 445]),  # NAS: SSH wins over SMB
        ]
        gw = guess_gateway(hosts)
        self.assertEqual(gw, "192.168.1.1")
        kinds = {h.ip: classify(h, gw) for h in hosts}
        self.assertEqual(kinds, {
            "192.168.1.1": "router", "192.168.1.30": "device", "192.168.1.20": "server",
            "192.168.1.42": "printer", "192.168.1.101": "pc", "192.168.1.10": "server",
        })


if __name__ == "__main__":
    unittest.main()
