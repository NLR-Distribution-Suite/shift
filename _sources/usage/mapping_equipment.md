# Mapping Equipment

Equipment mapping assigns physical equipment models — loads, voltage sources, transformers, and branches — to the nodes and edges of the distribution graph.

`EdgeEquipmentMapper` handles edge equipment (transformers and branches) automatically from a catalog. To control how **node** equipment (loads and sources) is assigned, extend `EdgeEquipmentMapper` and override `node_asset_equipment_mapping`.

## Example: Area-Based Load Mapper

The example below assigns load sizes based on the nearest parcel's footprint area. It uses a KDTree to find the closest parcel to each node, then maps the parcel area to a kW value.

**Prerequisites** — This example assumes you have already completed:
- [Fetching Parcels](fetching_parcels.md) → `parcels`
- [Building a Graph](building_graph.md) → `new_graph`
- [Mapping Phases](mapping_phases.md) → `phase_mapper`
- [Mapping Voltages](mapping_voltages.md) → `voltage_mapper`

### Load the Equipment Catalog

Any valid `DistributionSystem` can serve as an equipment catalog. Here we load one from a JSON file (created via a Ditto reader from SMARTDS models):

```python
from pathlib import Path
from gdm import DistributionSystem
import shift

MODELS_FOLDER = Path(shift.__file__).parent.parent.parent / "tests" / "models"
catalog_sys = DistributionSystem.from_json(MODELS_FOLDER / "p1rhs7_1247.json")
```

### Define the Custom Mapper

```python
from functools import cached_property

from shift import (
    EdgeEquipmentMapper,
    BaseVoltageMapper,
    BasePhaseMapper,
    ParcelModel,
    GeoLocation,
    NodeModel,
)

from gdm import (
    PhaseVoltageSourceEquipment,
    DistributionVoltageSource,
    VoltageSourceEquipment,
    PhaseLoadEquipment,
    DistributionLoad,
    LoadEquipment,
    Phase,
)
from gdm.quantities import ReactivePower, Reactance

from shapely.geometry import Polygon
from scipy.spatial import KDTree
from infrasys.quantities import ActivePower, Resistance, Voltage, Angle
from infrasys import System


def _get_parcel_points(parcels: list[ParcelModel]) -> list[GeoLocation]:
    """Extract a single GeoLocation per parcel."""
    return [
        p.geometry[0] if isinstance(p.geometry, list) else p.geometry
        for p in parcels
    ]


class AreaBasedLoadMapper(EdgeEquipmentMapper):
    """Map load kW to nodes based on the area of the nearest parcel."""

    def __init__(
        self,
        graph,
        catalog_sys: System,
        voltage_mapper: BaseVoltageMapper,
        phase_mapper: BasePhaseMapper,
        parcels: list[ParcelModel],
    ):
        self.parcels = parcels
        super().__init__(graph, catalog_sys, voltage_mapper, phase_mapper)

    def _get_area_for_node(self, node: NodeModel) -> float:
        """Return the footprint area of the parcel nearest to this node."""
        tree = KDTree(_get_parcel_points(self.parcels))
        _, idx = tree.query([[node.location.x, node.location.y]], k=1)
        nearest_parcel: ParcelModel = self.parcels[idx.flat[0]]
        if isinstance(nearest_parcel.geometry, list):
            return Polygon(nearest_parcel.geometry).area
        return 0.0

    @cached_property
    def node_asset_equipment_mapping(self):
        node_equipment = {}

        for node in self.graph.get_nodes():
            node_equipment[node.name] = {}
            area = self._get_area_for_node(node)

            # Simple area → kW heuristic
            if area > 10 and area < 30:
                kw = 1.2
            elif area <= 10:
                kw = 0.8
            else:
                kw = 1.3

            # Distribute load evenly across assigned phases
            phases = self.phase_mapper.node_phase_mapping[node.name] - {Phase.N}
            num_phase = len(phases)

            node_equipment[node.name][DistributionLoad] = LoadEquipment(
                name=f"load_{node.name}",
                phase_loads=[
                    PhaseLoadEquipment(
                        name=f"load_{node.name}_{idx}",
                        real_power=ActivePower(kw / num_phase, "kilowatt"),
                        reactive_power=ReactivePower(0, "kilovar"),
                        z_real=0,
                        i_real=0,
                        p_real=1,
                        z_imag=0,
                        i_imag=0,
                        p_imag=1,
                    )
                    for idx in range(num_phase)
                ],
            )

            # If this node hosts the voltage source, add source equipment
            if DistributionVoltageSource in node.assets:
                node_equipment[node.name][DistributionVoltageSource] = VoltageSourceEquipment(
                    name="vsource_test",
                    sources=[
                        PhaseVoltageSourceEquipment(
                            name=f"vsource_{idx}",
                            r0=Resistance(1e-5, "ohm"),
                            r1=Resistance(1e-5, "ohm"),
                            x0=Reactance(1e-5, "ohm"),
                            x1=Reactance(1e-5, "ohm"),
                            voltage=Voltage(12.47, "kilovolt"),
                            angle=Angle(0, "degree"),
                        )
                        for idx in range(3)
                    ],
                )

        return node_equipment
```

### Instantiate the Mapper

```python
eq_mapper = AreaBasedLoadMapper(
    new_graph,
    catalog_sys=catalog_sys,
    voltage_mapper=voltage_mapper,
    phase_mapper=phase_mapper,
    parcels=parcels,
)
```

## Next Step

With all three mappers ready (phase, voltage, equipment), proceed to [Building a System](building_system.md) to assemble the final distribution system model.