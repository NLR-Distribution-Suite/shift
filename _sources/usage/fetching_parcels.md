# Fetching Parcels

The first step in building a distribution model is obtaining building parcels — the geographic footprints of structures that will become load points in the network.

NREL-shift provides three functions for loading parcels, depending on your data source.

## From an Address or Coordinates

Use `parcels_from_location` to download parcels from OpenStreetMap. You can pass a place name, a `GeoLocation`, or a polygon of `GeoLocation` points.

```python
from shift import parcels_from_location, GeoLocation
from infrasys.quantities import Distance

# By address string
parcels = parcels_from_location("Fort Worth, TX", Distance(500, "m"))

# By coordinates
location = GeoLocation(longitude=-97.33, latitude=32.75)
parcels = parcels_from_location(location, Distance(500, "m"))

# By polygon (no distance needed — area is defined by the vertices)
polygon = [
    GeoLocation(-97.33, 32.75),
    GeoLocation(-97.32, 32.76),
    GeoLocation(-97.31, 32.75),
]
parcels = parcels_from_location(polygon)
```

Each element in the returned list is a `ParcelModel` whose `geometry` is either a single `GeoLocation` (point) or a list of `GeoLocation` points (polygon/multipolygon).

## From a CSV File

Use `parcels_from_csv` when you have parcel data in a CSV file. The only requirement is a `geometry` column containing WKT geometries. Supported geometry types: `Point`, `Polygon`, and `MultiPolygon`.

```python
from shift import parcels_from_csv

parcels = parcels_from_csv("my_parcels.csv")
```

## From a GeoDataFrame

If you already have a GeoPandas `GeoDataFrame`, convert it directly:

```python
from shift import parcels_from_geodataframe

parcels = parcels_from_geodataframe(gdf)
```

## Visualizing Parcels

Once you have parcels, you can plot them on an interactive map:

```python
from shift import PlotManager, GeoLocation, add_parcels_to_plot
import osmnx as ox

# Center the map on the same location
center = GeoLocation(*reversed(ox.geocode("Fort Worth, TX")))
plot_manager = PlotManager(center=center)
add_parcels_to_plot(parcels, plot_manager)
plot_manager.show()
```

## Next Step

With parcels in hand, proceed to [Building a Graph](building_graph.md) to cluster them and construct the distribution network topology.