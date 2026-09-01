# Building a Distribution System

With the distribution graph and all three mappers (phase, voltage, equipment) ready, you can assemble the final `DistributionSystem` — a Grid Data Models object that can be serialized to JSON or exported to simulator formats.

## Build and Export

```python
from shift import DistributionSystemBuilder
from pathlib import Path

# `new_graph` — DistributionGraph (see Building a Graph / Updating Branch Types)
# `phase_mapper` — from Mapping Phases
# `voltage_mapper` — from Mapping Voltages
# `eq_mapper` — from Mapping Equipment

builder = DistributionSystemBuilder(
    name="fort_worth_feeder",
    dist_graph=new_graph,
    phase_mapper=phase_mapper,
    voltage_mapper=voltage_mapper,
    equipment_mapper=eq_mapper,
)

system = builder.get_system()
```

## Serialize to JSON

```python
output_folder = Path("./models")
output_folder.mkdir(exist_ok=True)
system.to_json(output_folder / "fort_worth_feeder.json")
```

## Export to a Simulator

The `DistributionSystem` object is compatible with [Ditto](https://github.com/NLR-Distribution-Suite/ditto) writers for exporting to OpenDSS, CYME, Synergi, and other simulators:

```python
# Example (requires the Ditto package)
# from ditto.writers.opendss import OpenDSSWriter
# writer = OpenDSSWriter()
# writer.write(system, output_path="./opendss_model")
```

## What's Next

See the [Complete Example](complete_example.md) for the full pipeline in a single script, or the [API Reference](../API_REFERENCE.md) for detailed class documentation.