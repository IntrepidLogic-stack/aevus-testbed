"""Tests for OPC UA client security config + self-signed cert generation (P3)."""

from __future__ import annotations

from src.collectors.opcua_client import OPCUANodeSpec, _parse_security, load_opcua_config
from src.collectors.opcua_security import (
    DEFAULT_APP_URI,
    OPCUASecurity,
    ensure_client_cert,
)


def test_security_string_default():
    s = OPCUASecurity()
    assert s.security_string() == (
        "Basic256Sha256,SignAndEncrypt,certs/aevus_opcua_client_cert.der,certs/aevus_opcua_client_key.pem"
    )


def test_security_string_with_server_cert():
    s = OPCUASecurity(server_cert="certs/server.der")
    assert s.security_string().endswith(",certs/server.der")
    assert s.security_string().count(",") == 4


def test_ensure_client_cert_generates_valid_cert(tmp_path):
    from cryptography import x509

    cert = tmp_path / "c.der"
    key = tmp_path / "k.pem"
    ensure_client_cert(cert, key, application_uri="urn:test:aevus")
    assert cert.exists() and key.exists()
    # the ApplicationUri MUST be in the SubjectAltName or OPC UA servers reject the session
    loaded = x509.load_der_x509_certificate(cert.read_bytes())
    san = loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    uris = san.get_values_for_type(x509.UniformResourceIdentifier)
    assert "urn:test:aevus" in uris
    # clientAuth EKU present
    eku = loaded.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert any(o.dotted_string == "1.3.6.1.5.5.7.3.2" for o in eku)  # clientAuth


def test_ensure_client_cert_is_idempotent(tmp_path):
    cert = tmp_path / "c.der"
    key = tmp_path / "k.pem"
    ensure_client_cert(cert, key)
    first = cert.read_bytes()
    ensure_client_cert(cert, key)  # second call must NOT regenerate
    assert cert.read_bytes() == first


def test_parse_security_forms():
    assert _parse_security(None) is None
    assert _parse_security("Basic256Sha256,SignAndEncrypt,c.der,k.pem") == ("Basic256Sha256,SignAndEncrypt,c.der,k.pem")
    sec = _parse_security({"policy": "Basic256", "mode": "Sign", "auto_generate": False})
    assert isinstance(sec, OPCUASecurity)
    assert sec.policy == "Basic256"
    assert sec.mode == "Sign"
    assert sec.auto_generate is False
    assert sec.application_uri == DEFAULT_APP_URI  # default filled in


def test_secure_tagmap_parses_to_structured_security(tmp_path):
    p = tmp_path / "secure.yaml"
    p.write_text(
        "asset:\n"
        "  id: SITE-OPCUA\n"
        "  endpoint: opc.tcp://h:4840\n"
        "  security:\n"
        "    policy: Basic256Sha256\n"
        "    mode: SignAndEncrypt\n"
        "tags:\n"
        "  - {node: 'ns=2;s=X', metric: vibration, unit: mm/s}\n"
    )
    cfg = load_opcua_config(p)
    assert isinstance(cfg.security, OPCUASecurity)
    assert cfg.security.mode == "SignAndEncrypt"
    # the built collector carries the structured security through
    col = cfg.to_collector()
    assert isinstance(col.security, OPCUASecurity)


def test_shipped_secure_example_parses():
    from pathlib import Path

    ref = Path(__file__).resolve().parents[1] / "config" / "opcua" / "example_secure.yaml"
    cfg = load_opcua_config(ref)
    assert isinstance(cfg.security, OPCUASecurity)
    assert cfg.security.policy == "Basic256Sha256"
    assert cfg.security.mode == "SignAndEncrypt"


def test_specs_still_build():
    # sanity: OPCUANodeSpec unaffected by P3
    assert OPCUANodeSpec("ns=2;i=1", "vibration").metric == "vibration"
