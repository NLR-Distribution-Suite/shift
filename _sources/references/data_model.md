# Data Models

Core data structures used throughout NREL-shift.

## GeoLocation

```{eval-rst}
.. autoclass:: shift.GeoLocation
    :members:
```

## ParcelModel

```{eval-rst}
.. autopydantic_model:: shift.ParcelModel
    :members:
```

## GroupModel

```{eval-rst}
.. autopydantic_model:: shift.GroupModel
    :members:
```

## NodeModel

```{eval-rst}
.. autopydantic_model:: shift.NodeModel
    :members:
```

## EdgeModel

```{eval-rst}
.. autopydantic_model:: shift.EdgeModel
    :members:
```

## TransformerPhaseMapperModel

```{eval-rst}
.. autopydantic_model:: shift.TransformerPhaseMapperModel
    :members:
```

## TransformerVoltageModel

```{eval-rst}
.. autopydantic_model:: shift.TransformerVoltageModel
    :members:
```

## TransformerTypes

```{eval-rst}
.. autoclass:: shift.TransformerTypes
    :members:
```

## Type Aliases

- ``VALID_NODE_TYPES``: ``DistributionLoad | DistributionSolar | DistributionCapacitor | DistributionVoltageSource``
- ``VALID_EDGE_TYPES``: ``DistributionBranchBase | DistributionTransformer``