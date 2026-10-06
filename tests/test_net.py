"""src/net.py -- trust the OS certificate store unless a CA bundle is pinned."""

import sys
import types

import pytest

from src import net


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in net._OVERRIDE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(net, "_active", False)


def _fake_truststore(monkeypatch, injected):
    module = types.ModuleType("truststore")
    module.inject_into_ssl = lambda: injected.append(True)
    monkeypatch.setitem(sys.modules, "truststore", module)


def test_injects_the_system_store_when_nothing_is_pinned(monkeypatch):
    injected = []
    _fake_truststore(monkeypatch, injected)
    assert net.use_system_trust_store() is True
    assert injected == [True]
    assert "operating system" in net.trust_description()


def test_is_idempotent(monkeypatch):
    injected = []
    _fake_truststore(monkeypatch, injected)
    net.use_system_trust_store()
    net.use_system_trust_store()
    assert injected == [True]


@pytest.mark.parametrize("variable", ["SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"])
def test_an_explicit_ca_bundle_wins(monkeypatch, variable):
    injected = []
    _fake_truststore(monkeypatch, injected)
    monkeypatch.setenv(variable, "/corp/ca.pem")
    assert net.use_system_trust_store() is False
    assert injected == []
    assert variable in net.trust_description() and "/corp/ca.pem" in net.trust_description()


def test_a_failure_to_switch_never_raises(monkeypatch):
    module = types.ModuleType("truststore")

    def boom():
        raise RuntimeError("unsupported platform")

    module.inject_into_ssl = boom
    monkeypatch.setitem(sys.modules, "truststore", module)
    assert net.use_system_trust_store() is False
    assert "certifi" in net.trust_description()


def test_the_real_truststore_switches_contexts():
    # Real package, real ssl module: after injection a default context is truststore's.
    import ssl
    import subprocess

    code = (
        "import ssl; from src import net; assert net.use_system_trust_store();"
        "ctx = ssl.create_default_context(); print(type(ctx).__module__)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "truststore" in result.stdout
    assert ssl  # the parent process's ssl stays untouched
