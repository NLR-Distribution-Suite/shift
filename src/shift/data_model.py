from typing import Annotated, NamedTuple, Type, Optional
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, model_validator
from gdm.quantities import Voltage, ApparentPower, Distance
from gdm.systems.distribution.components import (
    DistributionLoad,
    DistributionSolar,
    DistributionCapacitor,
    DistributionVoltageSource,
    DistributionBranchBase,
    DistributionTransformer,
)
from infrasys import Location


class BaseComponent(BaseModel):
    """Base component used for shift model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class GeoLocation(NamedTuple):
    """Interface for geo location."""

    longitude: Annotated[
        float,
        Field(..., ge=-180, le=180, description="Longitude coordinate of the parcel."),
    ]
    latitude: Annotated[
        float, Field(..., ge=-90, le=90, description="Latitude coordinate of the parcel.")
    ]


class ParcelModel(BaseModel):
    """Interface for parcel model."""

    name: Annotated[str, Field(..., description="Name of the parcel.")]
    geometry: Annotated[
        list[GeoLocation] | GeoLocation, Field(..., description="Geo location for the parcel.")
    ]
    building_type: Annotated[str, Field(..., description="Type of building.")]
    city: Annotated[str, Field(..., description="City the parcel is locatied in.")]
    state: Annotated[str, Field(..., description="State the parcel is locatied in.")]
    postal_address: Annotated[
        str, Field(..., description="Postal code the parcel is locatied in.")
    ]


class GroupModel(BaseModel):
    """Interface for group model."""

    center: Annotated[GeoLocation, Field(..., description="Centre of the cluster.")]
    points: Annotated[
        list[GeoLocation], Field(..., description="List of points that belong to this cluster.")
    ]


class TransformerVoltageModel(BaseComponent):
    """Interface for transformer voltage model."""

    name: Annotated[str, Field(..., description="Name of the transformer.")]
    voltages: Annotated[list[Voltage], Field(..., description="List of transformer voltages.")]


class TransformerTypes(str, Enum):
    """Enumerator for transformer types for phase allocation."""

    THREE_PHASE = "THREE_PHASE"
    SINGLE_PHASE_PRIMARY_DELTA = "SINGLE_PHASE_PRIMARY_DELTA"
    SINGLE_PHASE = "SINGLE_PHASE"
    SPLIT_PHASE = "SPLIT_PHASE"
    SPLIT_PHASE_PRIMARY_DELTA = "SPLIT_PHASE_PRIMARY_DELTA"


class TransformerPhaseMapperModel(BaseModel):
    """Class interface for phase mapper model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    tr_name: str
    tr_type: TransformerTypes
    tr_capacity: ApparentPower
    location: Location


VALID_NODE_TYPES = Annotated[
    Type[DistributionLoad]
    | Type[DistributionSolar]
    | Type[DistributionCapacitor]
    | Type[DistributionVoltageSource],
    Field(..., description="Possible node types."),
]

VALID_EDGE_TYPES = Annotated[
    Type[DistributionBranchBase] | Type[DistributionTransformer],
    Field(..., description="Possible edge types."),
]


class NodeModel(BaseModel):
    """Interface for node model."""

    name: Annotated[str, Field(..., description="Name of the node.")]
    location: Annotated[Location, Field(..., description="Location of node.")]
    assets: Annotated[
        Optional[set[VALID_NODE_TYPES]],
        Field({}, description="Set of asset types attached to node."),
    ]


class EdgeModel(BaseModel):
    """Interface for edge model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: Annotated[str, Field(..., description="Name of the node.")]
    edge_type: Annotated[VALID_EDGE_TYPES, Field(..., description="Edge type.")]
    length: Annotated[Optional[Distance], Field(None, description="Length of edge.")]

    @model_validator(mode="after")
    def validate_fields(self):
        if self.edge_type is DistributionTransformer and self.length is not None:
            msg = f"{self.length=} must be None for {self.edge_type=}"
            raise ValueError(msg)

        if self.edge_type is DistributionBranchBase and self.length is None:
            msg = f"{self.length=} must not be None for {self.edge_type=}"
            raise ValueError(msg)
        return self
