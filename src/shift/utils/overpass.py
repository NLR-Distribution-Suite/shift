"""Shared Overpass endpoint helpers for OSMnx-based data fetches."""

from __future__ import annotations

import socket
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import osmnx as ox
from loguru import logger

# Public Overpass mirrors for automatic failover.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


class OverpassFallbackError(RuntimeError):
    """Raised when all Overpass endpoints fail."""

    def __init__(self, message: str, errors: list[str], debug_log: list[str]):
        super().__init__(message)
        self.errors = errors
        self.debug_log = debug_log


def get_overpass_url() -> str | None:
    """Return the currently configured OSMnx Overpass endpoint."""
    if hasattr(ox.settings, "overpass_url"):
        return getattr(ox.settings, "overpass_url")
    if hasattr(ox.settings, "overpass_endpoint"):
        return getattr(ox.settings, "overpass_endpoint")
    return None


def set_overpass_url(url: str) -> tuple[str | None, str | None]:
    """Set the OSMnx Overpass endpoint and return (attr_name, previous_value)."""
    if hasattr(ox.settings, "overpass_url"):
        old_value = getattr(ox.settings, "overpass_url")
        setattr(ox.settings, "overpass_url", url)
        return "overpass_url", old_value
    if hasattr(ox.settings, "overpass_endpoint"):
        old_value = getattr(ox.settings, "overpass_endpoint")
        setattr(ox.settings, "overpass_endpoint", url)
        return "overpass_endpoint", old_value
    return None, None


def restore_overpass_url(attr_name: str | None, value: str | None) -> None:
    """Restore a previously saved OSMnx Overpass endpoint setting."""
    if attr_name is not None:
        setattr(ox.settings, attr_name, value)


@contextmanager
def _overpass_timeouts(timeout_seconds: float | None) -> Iterator[None]:
    """Temporarily lower OSMnx/socket timeouts so unreachable mirrors fail fast."""
    old_timeout = getattr(ox.settings, "timeout", None)
    old_http_timeout = getattr(ox.settings, "requests_timeout", None)
    old_socket_timeout = socket.getdefaulttimeout()
    if timeout_seconds is not None:
        if old_timeout is not None:
            ox.settings.timeout = timeout_seconds
        if hasattr(ox.settings, "requests_timeout"):
            ox.settings.requests_timeout = timeout_seconds
        socket.setdefaulttimeout(timeout_seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old_socket_timeout)
        if timeout_seconds is not None:
            if old_timeout is not None:
                ox.settings.timeout = old_timeout
            if old_http_timeout is not None and hasattr(ox.settings, "requests_timeout"):
                ox.settings.requests_timeout = old_http_timeout


def _attempt_endpoint(
    endpoint: str, fetch_fn: Callable[[], Any]
) -> tuple[Any | None, bool, list[str], list[str]]:
    """Try a single Overpass endpoint.

    Returns ``(result, ok, errors, debug_log)``; the OSMnx endpoint setting is
    always restored before returning.
    """
    attr_name, old_value = set_overpass_url(endpoint)
    started = time.perf_counter()
    logger.debug(f"Trying Overpass endpoint: {endpoint}")
    debug_log = [f"Trying Overpass endpoint: {endpoint}"]
    try:
        result = fetch_fn()
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        cleaned = " ".join(str(exc).split())[:240]
        errors = [f"{endpoint}: {cleaned}"]
        debug_log.append(f"Failed via {endpoint} in {elapsed_ms}ms: {cleaned}")
        logger.debug(f"Overpass endpoint {endpoint} failed: {exc!s:.120}")
        return None, False, errors, debug_log
    else:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        debug_log.append(f"Success via {endpoint} in {elapsed_ms}ms")
        logger.debug(f"Success via {endpoint}")
        return result, True, [], debug_log
    finally:
        restore_overpass_url(attr_name, old_value)


def fetch_with_overpass_failover(
    fetch_fn: Callable[[], Any],
    *,
    timeout_seconds: float | None = 5.0,
) -> tuple[Any, str, list[str], list[str]]:
    """Run ``fetch_fn`` across the configured Overpass endpoint and public mirrors.

    Tries the currently configured OSMnx endpoint first (when set), then each
    public mirror in order, returning on the first success. The original
    endpoint setting is restored after every attempt.

    Parameters
    ----------
    fetch_fn : Callable[[], Any]
        Zero-argument callable performing one Overpass-backed fetch.
    timeout_seconds : float | None
        When set, OSMnx request timeouts and a hard socket default timeout are
        lowered to this value so unreachable mirrors fail fast. Pass ``None``
        to leave timeouts untouched (useful for long-running queries).

    Returns
    -------
    tuple[Any, str, list[str], list[str]]
        ``(result, endpoint_used, errors, debug_log)`` where ``errors`` and
        ``debug_log`` collect per-endpoint failures up to the successful one.

    Raises
    ------
    OverpassFallbackError
        When every endpoint fails; carries all per-endpoint errors.
    """
    endpoints: list[str] = []
    for url in [get_overpass_url(), *OVERPASS_MIRRORS]:
        if url and url not in endpoints:
            endpoints.append(url)

    errors: list[str] = []
    debug_log: list[str] = []
    with _overpass_timeouts(timeout_seconds):
        for endpoint in endpoints:
            result, ok, attempt_errors, attempt_log = _attempt_endpoint(endpoint, fetch_fn)
            errors.extend(attempt_errors)
            debug_log.extend(attempt_log)
            if ok:
                return result, endpoint, errors, debug_log

    raise OverpassFallbackError(
        f"Failed to fetch from all {len(endpoints)} Overpass endpoints.",
        errors=errors,
        debug_log=debug_log,
    )
