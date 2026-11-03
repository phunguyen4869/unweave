"""Host-header allowlist for the UI server (loopback by default, LAN hosts for Docker)."""

import os
import unittest
from unittest import mock

from unweave.webui.server import extra_allowed_hosts, host_allowed


class AllowedHostsTests(unittest.TestCase):
    def test_loopback_only_by_default(self):
        self.assertTrue(host_allowed("127.0.0.1:8765", 8765, set()))
        self.assertTrue(host_allowed("localhost:8765", 8765, set()))
        for host in ("localhost:9000", "192.168.1.50:8765", "evil.example:8765", ""):
            with self.subTest(host=host):
                self.assertFalse(host_allowed(host, 8765, set()))

    def test_listed_names_match_any_port(self):
        extra = {"192.168.1.50", "unweave.lan"}
        self.assertTrue(host_allowed("192.168.1.50:8080", 8765, extra))
        self.assertTrue(host_allowed("UNWEAVE.lan", 8765, extra))
        self.assertFalse(host_allowed("192.168.1.51:8765", 8765, extra))
        self.assertFalse(host_allowed("unweave.lan.evil.example", 8765, extra))

    def test_name_with_port_matches_only_that_port(self):
        extra = {"unweave.lan:8080"}
        self.assertTrue(host_allowed("unweave.lan:8080", 8765, extra))
        self.assertFalse(host_allowed("unweave.lan:9090", 8765, extra))

    def test_ipv6_and_wildcard(self):
        self.assertTrue(host_allowed("[fd00::5]:8765", 8765, {"fd00::5"}))
        self.assertTrue(host_allowed("anything:1", 8765, {"*"}))
        self.assertFalse(host_allowed("", 8765, {"*"}))

    def test_env_parsing(self):
        with mock.patch.dict(os.environ, {"UNWEAVE_ALLOWED_HOSTS": " 10.0.0.2 , Unweave.LAN,, "}):
            self.assertEqual(extra_allowed_hosts(), {"10.0.0.2", "unweave.lan"})
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(extra_allowed_hosts(), set())


if __name__ == "__main__":
    unittest.main()
