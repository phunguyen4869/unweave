import ssl
import sys
import unittest
import urllib.error
from unittest.mock import patch

from unweave import netutil


class NetutilTests(unittest.TestCase):
    def setUp(self):
        netutil._ssl_context.cache_clear()
        self.addCleanup(netutil._ssl_context.cache_clear)

    def test_verification_failure_becomes_actionable_message(self):
        failure = urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
        with patch.object(netutil.urllib.request, "urlopen", side_effect=failure):
            with self.assertRaises(netutil.CertificateProblem) as caught:
                netutil.urlopen("https://github.com/x/y", timeout=5)
        self.assertIn("github.com", str(caught.exception))
        self.assertIn("antivirus", str(caught.exception))
        # Existing `except URLError` handlers must keep catching it.
        self.assertIsInstance(caught.exception, urllib.error.URLError)

    def test_other_network_errors_pass_through(self):
        failure = urllib.error.URLError("no route to host")
        with patch.object(netutil.urllib.request, "urlopen", side_effect=failure):
            with self.assertRaises(urllib.error.URLError) as caught:
                netutil.urlopen("https://github.com/x/y", timeout=5)
        self.assertNotIsInstance(caught.exception, netutil.CertificateProblem)

    def test_no_custom_context_off_windows(self):
        with patch.object(netutil.sys, "platform", "linux"):
            self.assertIsNone(netutil._ssl_context())

    @unittest.skipUnless(sys.platform == "win32", "Windows verification")
    def test_windows_context_keeps_verification_on(self):
        context = netutil._ssl_context()
        self.assertIsNotNone(context)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    @unittest.skipUnless(sys.platform == "win32", "Windows verification")
    def test_falls_back_when_pip_truststore_is_unavailable(self):
        with patch.dict(sys.modules, {"pip._vendor": None}):
            self.assertIsNone(netutil._ssl_context())


if __name__ == "__main__":
    unittest.main()
