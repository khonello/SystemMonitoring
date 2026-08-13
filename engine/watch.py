"""Who is watching which client, and what that fact is used for.

One dict, admin id to client id, plus the reverse lookup. It answers two
questions that used to have no answer at all:

  - *Which admins should receive this client's telemetry?* Previously every
    admin received every client's, whether or not anyone had it on screen
    (`issues.md` D5). At the 50-client ceiling that is roughly 4,000 application
    rows every 30 seconds pushed to each console for nothing.
  - *Should this client sample fast?* A client nobody is watching reports on the
    recording intervals. A client somebody has selected samples every few
    seconds, so the view is live rather than a report that lands every half
    minute (`issues.md` C19).

**Selection is the subscription.** There is no separate "watch" control, and
deliberately so: an operator can forget a toggle, and the cost of forgetting
this one would land on someone else's machine as permanent fast sampling.

**Recording is not affected by anything in this module.** The persist step runs
before any relay and does not consult it. Whether anyone is watching changes
what reaches a screen and how often a client samples for the screen; it never
changes what is written down.

Module-level state, like `connections` and `client_info` — one Engine process,
one registry, and a class would buy nothing.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# admin_id -> the client_id that admin is watching. An admin watching nobody
# has no entry, rather than an entry with an empty value: "not watching" and
# "watching something falsy" should not be the same lookup.
_watching: dict[str, str] = {}


def set_watch(admin_id: str, client_id: str) -> tuple[str | None, str | None]:
    """Point `admin_id` at `client_id`. Empty `client_id` clears the watch.

    Returns (dropped, taken_up): the client that admin stopped watching and the
    one it started watching, each only if the change was real. The caller uses
    those to decide whether a client's sample rate needs changing at all, which
    is why they are returned rather than logged and forgotten.
    """
    previous = _watching.get(admin_id)
    target = client_id or None

    if previous == target:
        return None, None

    if target is None:
        _watching.pop(admin_id, None)
    else:
        _watching[admin_id] = target

    logger.debug("watch: %s now watching %s (was %s)", admin_id, target, previous)
    return previous, target


def clear_watch(admin_id: str) -> str | None:
    """Forget an admin entirely. Returns the client it had been watching.

    Called when an admin disconnects. Without it a departed console would hold
    a client at its fast sample rate indefinitely, which is precisely the
    "admin vanished" case the TTL on the client side exists to survive — but
    the TTL is the safety net, not the mechanism.
    """
    previous = _watching.pop(admin_id, None)
    if previous is not None:
        logger.debug("watch: %s disconnected, released %s", admin_id, previous)
    return previous


def watchers_of(client_id: str) -> list[str]:
    """Every admin currently watching `client_id`."""
    return [admin for admin, watched in _watching.items() if watched == client_id]


def is_watched(client_id: str) -> bool:
    """True while at least one admin has `client_id` selected."""
    return any(watched == client_id for watched in _watching.values())


def watched_clients() -> set[str]:
    """Every client with at least one watcher — what the renewal task walks."""
    return set(_watching.values())


def reset() -> None:
    """Drop all subscriptions. For tests, and for a fresh Engine process."""
    _watching.clear()
