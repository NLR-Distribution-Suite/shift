# Trinidad, Colorado example

This example builds synthetic distribution feeder models for Trinidad, Colorado, from prepared local address and road data, then plots all substations and feeders in an interactive HTML map. The source datasets and generated feeder JSON files are not included in the repository.

## Inputs

| Data | Original online resource | Local artifact used here |
| --- | --- | --- |
| Address points | [Colorado Information Marketplace](https://data.colorado.gov/) public geospatial data portal; search for the Colorado Master Address Database | `/Users/alatif/Downloads/Master_Address_Public.gdb`, layer `LasAnimas`, filtered to ZIP `81082` |
| Roads | [OpenStreetMap](https://www.openstreetmap.org/) data queried through [Overpass API](https://overpass-api.de/) | `data/trinidad/colorado.osm.pbf` |
| Substations | [OpenStreetMap](https://www.openstreetmap.org/) `power=substation` features queried through [Overpass API](https://overpass-api.de/) | Retrieved during the build; any cache is local |
| Equipment catalog | `tests/models/p1rhs7_1247.json` in this repository | Same local catalog |

Before running the example, users must obtain the address geodatabase from the Colorado Information Marketplace and prepare an OpenStreetMap road PBF covering Trinidad. Place the PBF at `data/trinidad/colorado.osm.pbf`, update the address geodatabase path in `examples/trinidad/build_trinidad_co.py` or the notebook, and ensure the equipment catalog is available at `tests/models/p1rhs7_1247.json`. The `data/trinidad` and `outputs/trinidad_co` directories are local working directories and are not part of the repository.

## Run the build

From the repository root, use the `shift` Conda environment:

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate shift
PYTHONPATH=src python examples/trinidad/build_trinidad_co.py
```

The build writes models using `DistributionSystem.to_json` to:

```text
outputs/trinidad_co/substation_<osm_id>/feeder_<index>.json
```

## Generate the map

```bash
PYTHONPATH=src:scripts python scripts/plot_trinidad_substations.py \
  --folder outputs/trinidad_co \
  --output examples/trinidad/trinidad_substations.html
```

Open [trinidad_substations.html](trinidad_substations.html) in a browser. The map includes primary and secondary network traces, buses, loads, a legend, and a dropdown for isolating individual feeders.

## Notebook

Open [trinidad_feeder_workflow.ipynb](trinidad_feeder_workflow.ipynb) to follow the workflow interactively:

1. Configure local data sources.
2. Filter Trinidad address points.
3. Derive the compact service polygon.
4. Configure and run the feeder model pipeline.
5. Verify `substation_<id>/feeder_<n>.json` exports.
6. Generate the all-substation HTML map.
