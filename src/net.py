"""Network trust setup, shared by every entry point that talks to the internet.

By default Python's HTTPS stack trusts the CA bundle that ships with `certifi`, not the
operating system's certificate store. On a corporate PC that inspects HTTPS traffic the
company's own root certificate lives only in the OS store (Keychain / Windows
Certificate Store), so every request fails with a certificate error until someone
exports a PEM file and points `SSL_CERT_FILE` at it (2026-10-06: the README used to
say exactly that). `use_system_trust_store()` makes the whole process trust the OS store
instead, via `truststore`, once at startup -- no PEM file needed.

An explicit `SSL_CERT_FILE` / `SSL_CERT_DIR` / `REQUESTS_CA_BUNDLE` still wins: someone
who set one meant it. Any failure to switch is swallowed and the default certifi bundle
stays in place -- trust setup must never stop the app from starting.
"""

import os

_OVERRIDE_VARIABLES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE")
_active = False


def trust_override() -> str | None:
    """The environment variable that pins an explicit CA bundle, if one is set."""
    for name in _OVERRIDE_VARIABLES:
        if os.environ.get(name):
            return name
    return None


def use_system_trust_store() -> bool:
    """Trust the operating system's certificate store for this process. True when it is
    (now) active; False when an explicit CA-bundle variable is set or `truststore` can't
    be used. Safe to call repeatedly."""
    global _active
    if _active:
        return True
    if trust_override() is not None:
        return False
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001 -- missing package, unsupported platform, ...
        return False
    _active = True
    return True


def trust_description() -> str:
    """One line for `--doctor`: which certificate source this process uses."""
    override = trust_override()
    if override:
        return f"explicit CA bundle ({override}={os.environ[override]})"
    if _active:
        return "operating system certificate store (truststore)"
    return "bundled certifi CA list (truststore unavailable)"
