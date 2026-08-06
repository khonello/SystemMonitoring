"""TLS tests, run against real handshakes rather than mocks.

Encryption is the kind of thing that appears to work while being wrong — a
context with verification quietly disabled behaves identically to a correct one
until someone is actually attacked. So these tests assert the failures as much
as the successes: a wrong certificate must be rejected, and a plaintext client
must not silently succeed.

Certificates are generated per session with openssl. If it is unavailable the
whole module skips rather than pretending to have tested anything.
"""

from __future__ import annotations

import asyncio
import ssl

import pytest
import pytest_asyncio

from common.tls import (
    CERT_FILE_NAME,
    KEY_FILE_NAME,
    TLS_IDENTITY,
    TLSConfigurationError,
    client_context,
    describe,
    server_context,
)
from scripts.generate_cert import generate, openssl_path

HOST = "127.0.0.1"

pytestmark = pytest.mark.skipif(
    openssl_path() is None, reason="openssl is required to generate test certificates"
)


def _make_cert(directory) -> tuple:
    """Generate a certificate pair into `directory`, returning both paths."""
    assert generate(directory, days=1, identity=TLS_IDENTITY, force=True) == 0
    return directory / CERT_FILE_NAME, directory / KEY_FILE_NAME


@pytest.fixture(scope="session")
def valid_cert(tmp_path_factory):
    """The Engine's own certificate and key."""
    return _make_cert(tmp_path_factory.mktemp("engine-certs"))


@pytest.fixture(scope="session")
def imposter_cert(tmp_path_factory):
    """A different certificate for the same identity.

    Stands in for a machine on the LAN impersonating the Engine: the name
    matches, the key does not.
    """
    return _make_cert(tmp_path_factory.mktemp("imposter-certs"))


async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    line = await reader.readline()
    writer.write(line)
    await writer.drain()
    writer.close()


@pytest_asyncio.fixture
async def tls_server(valid_cert):
    """A TLS listener using the Engine's certificate."""
    certfile, keyfile = valid_cert
    server = await asyncio.start_server(
        _echo, HOST, 0, ssl=server_context(certfile, keyfile)
    )
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------


def test_server_context_requires_a_certificate(tmp_path):
    with pytest.raises(TLSConfigurationError, match="Certificate not found"):
        server_context(tmp_path / "absent.pem", tmp_path / "absent-key.pem")


def test_server_context_requires_a_key(valid_cert, tmp_path):
    certfile, _ = valid_cert
    with pytest.raises(TLSConfigurationError, match="Private key not found"):
        server_context(certfile, tmp_path / "absent-key.pem")


def test_client_context_requires_the_pinned_certificate(tmp_path):
    with pytest.raises(TLSConfigurationError, match="certificate not found"):
        client_context(tmp_path / "absent.pem")


def test_client_context_verifies_by_default(valid_cert):
    """The two settings that make TLS meaningful rather than decorative."""
    certfile, _ = valid_cert
    context = client_context(certfile)

    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_contexts_refuse_obsolete_protocol_versions(valid_cert):
    certfile, keyfile = valid_cert

    assert server_context(certfile, keyfile).minimum_version >= ssl.TLSVersion.TLSv1_2
    assert client_context(certfile).minimum_version >= ssl.TLSVersion.TLSv1_2


def test_describe_states_the_transport_plainly():
    assert "ENABLED" in describe(True, None)
    assert "plaintext" in describe(False)


# ---------------------------------------------------------------------------
# Handshakes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pinned_client_connects_and_exchanges_data(tls_server, valid_cert):
    certfile, _ = valid_cert

    reader, writer = await asyncio.open_connection(
        HOST, tls_server,
        ssl=client_context(certfile),
        server_hostname=TLS_IDENTITY,
    )
    try:
        writer.write(b"hello\n")
        await writer.drain()

        assert await reader.readline() == b"hello\n"
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_connection_is_actually_encrypted(tls_server, valid_cert):
    certfile, _ = valid_cert

    reader, writer = await asyncio.open_connection(
        HOST, tls_server,
        ssl=client_context(certfile),
        server_hostname=TLS_IDENTITY,
    )
    try:
        negotiated = writer.get_extra_info("ssl_object")

        assert negotiated is not None
        assert negotiated.version() in {"TLSv1.2", "TLSv1.3"}
        assert negotiated.cipher() is not None
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_imposter_certificate_is_rejected(imposter_cert, valid_cert):
    """The point of pinning: a machine claiming to be the Engine, with the right
    name but the wrong key, must not be accepted."""
    imposter_certfile, imposter_keyfile = imposter_cert
    real_certfile, _ = valid_cert

    server = await asyncio.start_server(
        _echo, HOST, 0, ssl=server_context(imposter_certfile, imposter_keyfile)
    )
    port = server.sockets[0].getsockname()[1]

    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.open_connection(
                HOST, port,
                ssl=client_context(real_certfile),
                server_hostname=TLS_IDENTITY,
            )
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_wrong_hostname_is_rejected(tls_server, valid_cert):
    """Hostname checking is on, so the identity has to match."""
    certfile, _ = valid_cert

    with pytest.raises(ssl.SSLCertVerificationError):
        await asyncio.open_connection(
            HOST, tls_server,
            ssl=client_context(certfile),
            server_hostname="not-the-engine",
        )


@pytest.mark.asyncio
async def test_unverified_client_is_rejected(tls_server):
    """A client that does not pin the Engine's certificate gets nowhere, since
    the certificate is self-signed and chains to no public CA."""
    with pytest.raises(ssl.SSLCertVerificationError):
        await asyncio.open_connection(
            HOST, tls_server,
            ssl=ssl.create_default_context(),
            server_hostname=TLS_IDENTITY,
        )


@pytest.mark.asyncio
async def test_plaintext_client_cannot_talk_to_a_tls_server(tls_server):
    """It must fail rather than appear to work — a silent downgrade to
    plaintext is the failure mode this whole feature exists to prevent."""
    reader, writer = await asyncio.open_connection(HOST, tls_server)
    try:
        writer.write(b'{"type":"REGISTER"}\n')
        await writer.drain()

        # The server reads the JSON as a malformed ClientHello and drops the
        # connection. Whether that surfaces as a clean EOF or a reset is
        # platform-dependent; what matters is that the data is never echoed.
        try:
            reply = await asyncio.wait_for(reader.readline(), timeout=5)
        except (ConnectionError, ssl.SSLError):
            reply = b""

        assert reply == b"", "a TLS server must never echo plaintext back"
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_localhost_is_covered_by_the_certificate(tls_server, valid_cert):
    """A single-machine development setup should verify properly rather than
    needing verification switched off."""
    certfile, _ = valid_cert

    reader, writer = await asyncio.open_connection(
        HOST, tls_server,
        ssl=client_context(certfile),
        server_hostname="localhost",
    )
    writer.close()
