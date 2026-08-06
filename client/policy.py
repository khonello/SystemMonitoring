"""Access-control enforcement: website filtering and the application blacklist.

Website filtering rewrites the hosts file rather than running a proxy. A proxy
would filter by URL path and survive DNS-over-HTTPS, but it means shipping and
supervising another network service on every lab machine; the hosts file needs
nothing beyond write access to one file. Its limits are real and worth knowing:
it matches whole domains only, and a browser using DNS-over-HTTPS bypasses it.
Documented rather than hidden.

The blacklist/whitelist asymmetry is deliberate (README "Access Control"):
websites support both modes, applications are blacklist-only, because
whitelisting applications cannot reliably enumerate the OS and helper processes
that legitimate work depends on.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

import psutil

from client.state import POLICY_FILE, StateTampered, read_state, write_state
from common.constants import POLICY_MODE_BLACKLIST, POLICY_MODE_WHITELIST

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

HOSTS_PATH = (
    Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    if IS_WINDOWS
    else Path("/etc/hosts")
)

# Everything this tool manages sits between these markers, so the rest of the
# file — which may carry unrelated entries an administrator put there — is
# never touched.
BEGIN_MARKER = "# BEGIN LabMonitor managed block"
END_MARKER = "# END LabMonitor managed block"

BLOCK_ADDRESS = "127.0.0.1"

# Whitelist mode still has to let the machine reach the Engine and resolve
# essentials, or the agent blocks itself out of its own network.
WHITELIST_ALWAYS_ALLOWED: frozenset[str] = frozenset({"localhost"})


# ---------------------------------------------------------------------------
# Hosts file
# ---------------------------------------------------------------------------


def render_managed_block(mode: str, urls: Iterable[str]) -> str:
    """Build the managed section for a policy.

    Whitelist mode cannot be expressed in a hosts file — there is no "block
    everything except" entry — so it is approximated by blocking a known set of
    popular domains and relying on the Engine to send a complete blocklist.
    That limitation is surfaced to the operator rather than pretended away.
    """
    entries = sorted({_normalise(url) for url in urls if _normalise(url)})

    lines = [BEGIN_MARKER, f"# mode={mode}"]

    if mode == POLICY_MODE_WHITELIST:
        lines.append(
            "# Whitelist mode: a hosts file cannot express 'deny by default', so"
        )
        lines.append(
            "# these are the domains the Engine listed as NOT permitted."
        )

    for domain in entries:
        if domain in WHITELIST_ALWAYS_ALLOWED:
            continue
        lines.append(f"{BLOCK_ADDRESS} {domain}")
        # Browsers reach www.example.com without the bare domain resolving, so
        # both forms are needed for the block to actually bite.
        if not domain.startswith("www."):
            lines.append(f"{BLOCK_ADDRESS} www.{domain}")

    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def _normalise(url: str) -> str:
    """Reduce a URL or domain to a bare hostname."""
    cleaned = url.strip().lower()
    for prefix in ("https://", "http://"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    cleaned = cleaned.split("/", 1)[0].split(":", 1)[0]
    return cleaned.strip()


def strip_managed_block(content: str) -> str:
    """Remove any previously managed section, leaving everything else intact."""
    lines = content.splitlines()
    output: list[str] = []
    inside = False

    for line in lines:
        if line.strip() == BEGIN_MARKER:
            inside = True
            continue
        if line.strip() == END_MARKER:
            inside = False
            continue
        if not inside:
            output.append(line)

    return "\n".join(output).rstrip() + "\n"


def apply_website_policy(mode: str, urls: list[str], action: str = "block") -> dict[str, Any]:
    """Write a website policy into the hosts file.

    Requires administrator rights; the agent runs as a service so it has them,
    but a developer running it by hand will not.
    """
    if mode not in {POLICY_MODE_BLACKLIST, POLICY_MODE_WHITELIST}:
        return {"status": "error", "message": f"Unknown policy mode: {mode!r}"}

    try:
        existing = HOSTS_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "error", "message": f"Cannot read hosts file: {exc}"}

    base = strip_managed_block(existing)

    if action == "unblock":
        updated, applied = base, []
    else:
        if action == "replace":
            applied = list(urls)
        else:  # "block" merges with whatever was already managed
            applied = sorted(set(_managed_domains(existing)) | {_normalise(u) for u in urls})
        updated = base + "\n" + render_managed_block(mode, applied)

    try:
        _write_hosts(updated)
    except PermissionError:
        return {
            "status": "error",
            "message": "Writing the hosts file needs administrator rights",
        }
    except OSError as exc:
        return {"status": "error", "message": f"Cannot write hosts file: {exc}"}

    cache_policy({"mode": mode, "urls": applied, "action": action})
    _flush_dns()

    logger.info("Website policy applied: mode=%s, %d domains", mode, len(applied))
    return {
        "status": "success",
        "message": f"{mode} policy applied to {len(applied)} domains",
        "domains": len(applied),
    }


def _managed_domains(content: str) -> list[str]:
    """Domains currently inside the managed block."""
    domains: list[str] = []
    inside = False

    for line in content.splitlines():
        stripped = line.strip()
        if stripped == BEGIN_MARKER:
            inside = True
            continue
        if stripped == END_MARKER:
            break
        if inside and stripped and not stripped.startswith("#"):
            parts = stripped.split()
            if len(parts) >= 2 and not parts[1].startswith("www."):
                domains.append(parts[1])

    return domains


def _write_hosts(content: str) -> None:
    """Replace the hosts file, keeping a one-time backup of the original."""
    backup = HOSTS_PATH.with_suffix(".labmonitor.bak")
    if not backup.exists():
        try:
            shutil.copy2(HOSTS_PATH, backup)
        except OSError:
            logger.warning("Could not back up the hosts file", exc_info=True)

    HOSTS_PATH.write_text(content, encoding="utf-8")


def _flush_dns() -> None:
    """Drop the resolver cache so the new policy takes effect immediately."""
    if not IS_WINDOWS:
        return
    try:
        import subprocess

        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True, timeout=10, check=False,
        )
    except Exception:
        logger.debug("DNS flush failed", exc_info=True)


# ---------------------------------------------------------------------------
# Application blacklist
# ---------------------------------------------------------------------------


def cache_policy(policy: dict[str, Any]) -> None:
    """Remember the active policy so it survives an Engine outage."""
    try:
        current = load_cached_policy()
        current.update(policy)
        write_state(POLICY_FILE, current)
    except Exception:
        logger.warning("Could not cache the policy", exc_info=True)


def load_cached_policy() -> dict[str, Any]:
    try:
        return read_state(POLICY_FILE) or {}
    except StateTampered as exc:
        logger.error("Policy cache tampered with (%s) - ignoring it", exc)
        return {}


def set_app_blacklist(process_names: list[str]) -> dict[str, Any]:
    """Store the application blacklist. Enforcement is continuous, not one-off."""
    normalised = sorted({name.strip().lower() for name in process_names if name.strip()})
    cache_policy({"app_blacklist": normalised})

    logger.info("Application blacklist set: %d entries", len(normalised))
    return {
        "status": "success",
        "message": f"Blacklist set to {len(normalised)} applications",
        "blocked": normalised,
    }


def enforce_app_blacklist() -> list[str]:
    """Terminate any running blacklisted application.

    Called on the monitoring cycle rather than once, because blocking a launch
    means killing it shortly after it starts — there is no pre-launch hook
    without a kernel driver, which is well outside this project's scope.

    Returns the process names actually terminated.
    """
    blacklist = set(load_cached_policy().get("app_blacklist", []))
    if not blacklist:
        return []

    terminated: list[str] = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name in blacklist:
                proc.terminate()
                terminated.append(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            logger.debug("Could not terminate a blacklisted process", exc_info=True)

    if terminated:
        logger.info("Terminated blacklisted applications: %s", terminated)

    return terminated
