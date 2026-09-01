"""Parcel fetching tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer

from shift.mcp_server.serializers import serialize_parcel
from shift.utils.overpass import OverpassFallbackError, fetch_with_overpass_failover


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

    return fetch_with_overpass_failover(
        lambda: parcels_from_location(location, Distance(distance_meters, "m")),
        timeout_seconds=None,
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
