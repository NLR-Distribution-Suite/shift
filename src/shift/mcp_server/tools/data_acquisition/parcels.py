"""Parcel fetching tools."""

from __future__ import annotations

import json
import time

from mcp.server import MCPServer

from shift.mcp_server.serializers import serialize_parcel


class OverpassFallbackError(RuntimeError):
    """Raised when all Overpass endpoints fail during parcel fetch."""

    def __init__(self, message: str, errors: list[str], debug_log: list[str]):
        super().__init__(message)
        self.errors = errors
        self.debug_log = debug_log


def _set_overpass_endpoint(url: str) -> tuple[str | None, str | None]:
    """Set OSMnx overpass endpoint for this process and return previous value.

    Returns a tuple of (attribute_name, previous_value). If no compatible
    setting is found, returns (None, None).
    """
    import osmnx as ox

    if hasattr(ox.settings, "overpass_url"):
        old_value = getattr(ox.settings, "overpass_url")
        setattr(ox.settings, "overpass_url", url)
        return "overpass_url", old_value

    if hasattr(ox.settings, "overpass_endpoint"):
        old_value = getattr(ox.settings, "overpass_endpoint")
        setattr(ox.settings, "overpass_endpoint", url)
        return "overpass_endpoint", old_value

    return None, None


def _restore_overpass_endpoint(attr_name: str | None, value: str | None) -> None:
    """Restore OSMnx overpass endpoint setting after a temporary override."""
    if attr_name is None:
        return

    import osmnx as ox

    setattr(ox.settings, attr_name, value)


def _clean_error_message(error_text: str, max_len: int = 600) -> str:
    """Trim verbose HTML-heavy downstream errors for MCP responses."""
    normalized = " ".join(str(error_text).split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[:max_len] + " ..."


def _fetch_with_overpass_fallback(location, distance_meters: float):
    """Fetch parcels with automatic retries across public Overpass mirrors."""
    from gdm.quantities import Distance
    from shift.parcel import parcels_from_location

    import osmnx as ox

    default_url = None
    if hasattr(ox.settings, "overpass_url"):
        default_url = getattr(ox.settings, "overpass_url")
    elif hasattr(ox.settings, "overpass_endpoint"):
        default_url = getattr(ox.settings, "overpass_endpoint")

    endpoints = [
        default_url,
        "https://overpass-api.de/api",
        "https://overpass.kumi.systems/api",
        "https://maps.mail.ru/osm/tools/overpass/api",
    ]

    # Preserve order while removing None/empty and duplicates.
    seen = set()
    unique_endpoints = []
    for endpoint in endpoints:
        if not endpoint or endpoint in seen:
            continue
        seen.add(endpoint)
        unique_endpoints.append(endpoint)

    errors: list[str] = []
    debug_log: list[str] = []
    for endpoint in unique_endpoints:
        attr_name = None
        old_value = None
        started = time.perf_counter()
        debug_log.append(f"Trying Overpass endpoint: {endpoint}")
        try:
            attr_name, old_value = _set_overpass_endpoint(endpoint)
            parcels = parcels_from_location(location, Distance(distance_meters, "m"))
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            debug_log.append(f"Success via {endpoint} in {elapsed_ms}ms")
            return parcels, endpoint, errors, debug_log
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            cleaned = _clean_error_message(str(exc), max_len=240)
            errors.append(f"{endpoint}: {cleaned}")
            debug_log.append(f"Failed via {endpoint} in {elapsed_ms}ms: {cleaned}")
        finally:
            _restore_overpass_endpoint(attr_name, old_value)

    raise OverpassFallbackError(
        "Failed to fetch parcels from all Overpass endpoints.",
        errors=errors,
        debug_log=debug_log,
    )


def _parse_location(location: str):
    """Parse a location string into a GeoLocation or return the string."""
    from shift.data_model import GeoLocation

    if "," in location:
        parts = location.split(",")
        if len(parts) == 2:
            try:
                lon, lat = float(parts[0].strip()), float(parts[1].strip())
                return GeoLocation(lon, lat)
            except ValueError:
                pass
    return location


def register(mcp: MCPServer) -> None:  # noqa: C901
    """Register parcel tools on the MCPServer instance."""

    @mcp.tool()
    def set_local_pbf(pbf_path: str) -> str:
        """Configure a local OpenStreetMap ``.pbf`` file for offline extraction.

        Once set, parcel and road fetches use ``osmium`` to cut the requested
        area out of this file instead of querying public Overpass servers.

        Args:
            pbf_path: Absolute path to a local ``.osm.pbf`` file.

        Returns:
            JSON confirmation with the configured path.
        """
        try:
            from pathlib import Path
            from shift.openstreet_roads import set_local_pbf as _set_local_pbf

            if not pbf_path or not Path(pbf_path).exists():
                return json.dumps({"success": False, "error": f"PBF file not found: {pbf_path}"})
            _set_local_pbf(pbf_path)
            return json.dumps({"success": True, "pbf_path": pbf_path})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"success": False, "error": _clean_error_message(str(exc))})

    @mcp.tool()
    def fetch_parcels(
        location: str,
        distance_meters: float = 500.0,
    ) -> str:
        """Fetch building parcels from OpenStreetMap for a given location.

        Retrieves building footprints and metadata (building type, address)
        within the specified radius of a location.

        Args:
            location: Address string (e.g. "Fort Worth, TX") or coordinates
                      as "longitude,latitude" (e.g. "-97.33,32.75").
            distance_meters: Search radius in meters (default 500, max 5000).

        Returns:
            JSON array of parcel objects with name, building_type, city,
            state, postal_address, and geometry.
        """
        try:
            distance_meters = min(distance_meters, 5000.0)
            loc = _parse_location(location)
            parcels, endpoint_used, endpoint_errors, debug_log = _fetch_with_overpass_fallback(
                loc,
                distance_meters,
            )

            if parcels is None:
                return json.dumps(
                    {
                        "success": True,
                        "parcels": [],
                        "count": 0,
                        "overpass_endpoint": endpoint_used,
                        "overpass_failovers": endpoint_errors,
                        "debug_log": debug_log,
                    }
                )

            result = [serialize_parcel(p) for p in parcels]
            return json.dumps(
                {
                    "success": True,
                    "parcels": result,
                    "count": len(result),
                    "overpass_endpoint": endpoint_used,
                    "overpass_failovers": endpoint_errors,
                    "debug_log": debug_log,
                }
            )

        except OverpassFallbackError as exc:
            return json.dumps(
                {
                    "success": False,
                    "error": _clean_error_message(str(exc)),
                    "overpass_failovers": exc.errors,
                    "debug_log": exc.debug_log,
                }
            )
        except Exception as exc:
            return json.dumps({"success": False, "error": _clean_error_message(str(exc))})

    @mcp.tool()
    def fetch_parcels_in_polygon(
        coordinates: list[dict[str, float]],
    ) -> str:
        """Fetch building parcels within a polygon boundary.

        Args:
            coordinates: List of {longitude, latitude} dicts defining the
                         polygon vertices. At least 3 points required.

        Returns:
            JSON array of parcel objects found within the polygon.
        """
        try:
            from shift.data_model import GeoLocation
            from shift.openstreet_roads import get_local_pbf

            if len(coordinates) < 3:
                return json.dumps(
                    {"success": False, "error": "At least 3 coordinate points required."}
                )

            geo_points = [GeoLocation(c["longitude"], c["latitude"]) for c in coordinates]

            # Prefer the local PBF when configured: offline, fast, and avoids
            # flaky public Overpass endpoints. Fall back to Overpass on failure.
            if get_local_pbf():
                try:
                    from shift.parcel import parcels_from_pbf

                    pbf_parcels = parcels_from_pbf(geo_points)
                    result = [serialize_parcel(p) for p in pbf_parcels]
                    return json.dumps(
                        {
                            "success": True,
                            "parcels": result,
                            "count": len(result),
                            "source": "local_pbf",
                        }
                    )
                except Exception:  # noqa: BLE001
                    pbf_parcels = None  # PBF failed; fall through to Overpass

            parcels, endpoint_used, endpoint_errors, debug_log = _fetch_with_overpass_fallback(
                geo_points,
                500.0,
            )

            if parcels is None:
                return json.dumps(
                    {
                        "success": True,
                        "parcels": [],
                        "count": 0,
                        "overpass_endpoint": endpoint_used,
                        "overpass_failovers": endpoint_errors,
                        "debug_log": debug_log,
                    }
                )

            result = [serialize_parcel(p) for p in parcels]
            return json.dumps(
                {
                    "success": True,
                    "parcels": result,
                    "count": len(result),
                    "overpass_endpoint": endpoint_used,
                    "overpass_failovers": endpoint_errors,
                    "debug_log": debug_log,
                }
            )

        except OverpassFallbackError as exc:
            return json.dumps(
                {
                    "success": False,
                    "error": _clean_error_message(str(exc)),
                    "overpass_failovers": exc.errors,
                    "debug_log": exc.debug_log,
                }
            )
        except Exception as exc:
            return json.dumps({"success": False, "error": _clean_error_message(str(exc))})
