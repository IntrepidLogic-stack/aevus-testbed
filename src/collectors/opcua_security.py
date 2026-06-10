"""OPC UA client security (P3): structured config + self-signed client certificate.

A real OPC UA connection must run over an encrypted, signed channel authenticated by
a client certificate — never anonymous/``None`` against a production server. This
module:

* models the security config (policy, message mode, cert/key paths, optional
  server-cert pin, application URI),
* generates a spec-compliant self-signed client certificate if one is missing
  (the ApplicationUri MUST appear in the cert's SubjectAltName or OPC UA servers
  reject the session), and
* renders the ``asyncua`` security string.

``Security=None`` remains available ONLY for public simulation servers; the tag-map
template ships with it null and a warning. Read-only still applies everywhere — this
module changes how we connect, never that we only read.
"""

from __future__ import annotations

import contextlib
import datetime
import socket
from dataclasses import dataclass
from pathlib import Path

DEFAULT_APP_URI = "urn:intrepidlogic:aevus:opcua-client"
DEFAULT_CERT = "certs/aevus_opcua_client_cert.der"
DEFAULT_KEY = "certs/aevus_opcua_client_key.pem"


@dataclass(frozen=True)
class OPCUASecurity:
    """Encrypted-channel security config for an OPC UA client connection."""

    policy: str = "Basic256Sha256"
    mode: str = "SignAndEncrypt"
    client_cert: str = DEFAULT_CERT
    client_key: str = DEFAULT_KEY
    server_cert: str | None = None  # optional: pin/trust a specific server cert
    application_uri: str = DEFAULT_APP_URI
    auto_generate: bool = True  # create a self-signed client cert if missing

    def security_string(self) -> str:
        """Render the ``asyncua`` set_security_string argument.

        Format: ``<Policy>,<Mode>,<client_cert>,<client_key>[,<server_cert>]``.
        """
        parts = [self.policy, self.mode, self.client_cert, self.client_key]
        if self.server_cert:
            parts.append(self.server_cert)
        return ",".join(parts)


def ensure_client_cert(
    cert_path: str | Path,
    key_path: str | Path,
    application_uri: str = DEFAULT_APP_URI,
    common_name: str = "Aevus OPC UA Client",
) -> None:
    """Create a self-signed client cert + key at the given paths if either is missing.

    No-op when both files already exist. The certificate carries the ApplicationUri in
    its SubjectAltName (required by OPC UA), clientAuth EKU, and a 10-year validity. The
    private key is written unencrypted PEM (mode 0600); keep it out of version control.
    """
    cert_p, key_p = Path(cert_path), Path(key_path)
    if cert_p.exists() and key_p.exists():
        return

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    cert_p.parent.mkdir(parents=True, exist_ok=True)
    key_p.parent.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Intrepid Logic LLC"),
        ]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=True,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            # ApplicationUri is REQUIRED by OPC UA; DNS hostnames satisfy servers that
            # also check DNSNames (deduped, empties dropped).
            x509.SubjectAlternativeName(
                [x509.UniformResourceIdentifier(application_uri)] + [x509.DNSName(h) for h in _san_hostnames()]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    key_p.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    with contextlib.suppress(OSError):
        key_p.chmod(0o600)


def _san_hostnames() -> list[str]:
    """Deduped, non-empty DNS hostnames for the cert SAN (host, FQDN, localhost)."""
    names: list[str] = []
    with contextlib.suppress(OSError):
        names.append(socket.gethostname())
    with contextlib.suppress(OSError):
        names.append(socket.getfqdn())
    names.append("localhost")
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out
