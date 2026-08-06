#!/usr/bin/env python3
"""Generate the Engine's self-signed TLS certificate.

    python -m scripts.generate_cert

Shells out to openssl rather than adding a Python crypto dependency: openssl is
already present in WSL (where the Engine runs) and in Git for Windows, and a
certificate is generated once per deployment rather than at runtime.

The certificate is issued for the fixed name `labmonitor-engine`, not for an IP
address. Clients dial whatever address the Engine has but verify against that
name, so the Engine can move between IPs — or sit on DHCP — without reissuing
anything or disabling hostname checking.

**The private key never leaves the Engine.** Only `engine-cert.pem` is
distributed, and it is public information by design: it is what clients pin.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from common.tls import (
    CERT_FILE_NAME,
    KEY_FILE_NAME,
    TLS_IDENTITY,
    default_cert_dir,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DAYS = 825  # Comfortably longer than a final-year project.


# Git for Windows ships openssl but only puts it on Git Bash's PATH, so a
# script launched from PowerShell or an IDE will not see it. Checking the known
# install locations avoids "openssl not found" on a machine that plainly has it.
_WINDOWS_FALLBACKS: tuple[str, ...] = (
    r"C:\Program Files\Git\usr\bin\openssl.exe",
    r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
    r"C:\Program Files (x86)\Git\mingw64\bin\openssl.exe",
)


def openssl_path() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found

    if sys.platform == "win32":
        for candidate in _WINDOWS_FALLBACKS:
            if Path(candidate).exists():
                return candidate

    return None


def generate(cert_dir: Path, days: int, identity: str, force: bool) -> int:
    openssl = openssl_path()
    if openssl is None:
        print("openssl not found on PATH.", file=sys.stderr)
        print("  WSL:     sudo apt install openssl", file=sys.stderr)
        print("  Windows: it ships with Git for Windows (Git Bash)", file=sys.stderr)
        return 1

    cert_dir.mkdir(parents=True, exist_ok=True)
    certfile = cert_dir / CERT_FILE_NAME
    keyfile = cert_dir / KEY_FILE_NAME

    if certfile.exists() and not force:
        print(f"{certfile} already exists. Pass --force to replace it.")
        print("Replacing it means redistributing the certificate to every "
              "client and admin machine.")
        return 1

    # SANs carry the identity. localhost and 127.0.0.1 are included so a
    # single-machine development setup can verify properly too, rather than
    # needing verification turned off.
    san = f"DNS:{identity},DNS:localhost,IP:127.0.0.1"

    command = [
        openssl, "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(keyfile),
        "-out", str(certfile),
        "-days", str(days),
        "-nodes",                       # no passphrase: the Engine starts unattended
        "-subj", f"/CN={identity}",
        "-addext", f"subjectAltName={san}",
        "-addext", "basicConstraints=critical,CA:FALSE",
        "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
        "-addext", "extendedKeyUsage=serverAuth",
    ]

    print(f"Generating a certificate for '{identity}', valid {days} days...")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)

    if completed.returncode != 0:
        print("openssl failed:", file=sys.stderr)
        print(completed.stderr.strip(), file=sys.stderr)
        return 1

    # The key is the one secret here. Best effort on Windows; the installer
    # applies proper ACLs on a real deployment.
    try:
        keyfile.chmod(0o600)
    except OSError:
        pass

    print(f"\n  certificate  {certfile}")
    print(f"  private key  {keyfile}")
    print("\nNext steps:")
    print(f"  1. Keep {KEY_FILE_NAME} on the Engine only - never distribute it.")
    print(f"  2. Copy {CERT_FILE_NAME} to each client and admin machine.")
    print("     It is public by design: clients pin it to recognise the Engine.")
    print("  3. Restart the Engine; it picks the certificate up automatically.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Engine's TLS certificate")
    parser.add_argument("--dir", type=Path, default=default_cert_dir(REPO_ROOT))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--identity", default=TLS_IDENTITY)
    parser.add_argument("--force", action="store_true",
                        help="replace an existing certificate")
    args = parser.parse_args(argv)

    return generate(args.dir, args.days, args.identity, args.force)


if __name__ == "__main__":
    sys.exit(main())
