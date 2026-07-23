# UI Studio

The SHIFT UI Studio provides a browser-based workflow for building and comparing synthetic feeder topologies using the same core primitives as the Python API.

## Install

```bash
pip install -e ".[ui]"
```

## Run

```bash
shift-ui-server
```

Open `http://127.0.0.1:8000`.

## Current Workflow (v0.1 UI slice)

1. Fetch parcels by address or `longitude,latitude`.
2. Cluster parcels using K-means.
3. Select source location from map click.
4. Choose network preset and optional strategy overrides.
5. Build one graph or compare two preset builds.

## Available Network Presets

- `balanced_default`: `SteinerTreeStrategy` + `MeshSteinerStrategy`
- `road_optimized`: `WeightedSteinerTreeStrategy` + `OpenStreetSecondaryStrategy`
- `full_road_exploration`: `FullRoadGraphStrategy` + `HubLineStrategy`

## Exposed API Endpoints

- `GET /api/health`
- `GET /api/options`
- `POST /api/parcels/fetch`
- `POST /api/clusters/build`
- `POST /api/graph/build`
- `POST /api/graph/compare`
- `GET /api/graph/{graph_id}/transformers`
- `POST /api/mapper/phase`
- `POST /api/mapper/voltage`
- `POST /api/mapper/equipment`
- `POST /api/system/build`
- `POST /api/system/export`
- `GET /api/system/{system_name}/download`
- `GET /api/session/summary`

## Notes

- Session state is in-memory and resets when the server restarts.
- UI compare mode is intended for rapid topology exploration and metric inspection.
- Mapper/system endpoints are available and can be progressively surfaced in the UI controls.
