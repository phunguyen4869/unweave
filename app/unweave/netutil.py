"""HTTPS for the app's own downloads, with certificates verified by Windows when possible."""

from __future__ import annotations

from functools import lru_cache
import ssl
import sys
import urllib.error
import urllib.request


class CertificateProblem(urllib.error.URLError):
    """A server's certificate could not be verified. A URLError, so existing network
    error handling still applies, but with a message the user can act on."""

    def __str__(self) -> str:
        return str(self.reason)


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext | None:
    """Python only reads the roots already in the Windows store, but Windows fetches
    missing roots on demand, so a healthy PC can fail with "unable to get local issuer
    certificate". truststore asks Windows to verify instead, as pip does. Importing it
    from pip means the first downloads work before any package is installed."""
    if sys.platform != "win32":
        return None
    try:
        from pip._vendor import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return None  # Stripped runtime or changed pip: urllib's default verification.


def urlopen(url, *, timeout: float):
    """urllib.request.urlopen with the context above. Verification is never disabled."""
    try:
        return urllib.request.urlopen(url, timeout=timeout, context=_ssl_context())
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ssl.SSLCertVerificationError):
            raise
        address = getattr(url, "full_url", url)
        host = urllib.request.urlparse(address).hostname or address
        raise CertificateProblem(
            f"Could not verify the secure connection to {host}. Check that this PC's date and "
            "time are correct, then try turning off HTTPS scanning in your antivirus, or any "
            "VPN or proxy."
        ) from error
