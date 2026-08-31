""" " Test for getting parcels."""

from unittest import mock

import pytest
from infrasys.quantities import Distance
import geopandas as gpd
from shapely import Point, Polygon

from shift import (
    GeoLocation,
    ParcelModel,
    parcels_from_location,
    parcels_from_geodataframe,
    parcels_from_gis,
    OSMParcelFieldMapper,
    GISParcelFieldMapper,
)
from shift.exceptions import InvalidInputError

GET_PARCEL_INPUTS = [
    ["Fort Worth, TX", Distance(300, "m")],
    [GeoLocation(longitude=-97.3, latitude=32.75), Distance(300, "m")],
    [
        [
            GeoLocation(-122.29262, 37.83639),
            GeoLocation(-122.28095, 37.82972),
            GeoLocation(-122.29213, 37.82768),
            GeoLocation(-122.29262, 37.83639),
        ]
    ],
]


@pytest.fixture
def mock_ox():
    """Fixture for mocking osmnx package."""
    with mock.patch("shift.parcel.ox") as mock_ox:
        yield mock_ox


def get_sample_geo_dataframe():
    """Function to return sample geo dataframe."""
    return gpd.GeoDataFrame(
        geometry=[Point(1, 1), Polygon([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]])]
    )


def test_get_parcels_with_address(mock_ox):
    """Test get parcel with address."""
    mock_ox.features_from_address.return_value = get_sample_geo_dataframe()
    result = parcels_from_location("Fort Worth, Texas", Distance(100, "m"))

    mock_ox.features_from_address.assert_called_once_with(
        "Fort Worth, Texas", {"building": True}, dist=100
    )

    assert len(result) == 2
    assert isinstance(result[0], ParcelModel)


def test_get_parcels_with_point(mock_ox):
    """Test function to test get parcels from point."""
    mock_ox.features_from_point.return_value = gpd.GeoDataFrame(
        geometry=[Point(1, 1), Polygon([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]])]
    )

    result = parcels_from_location(
        GeoLocation(longitude=-97.3, latitude=32.75), Distance(300, "m")
    )
    mock_ox.features_from_point.assert_called_once_with(
        [32.75, -97.3], {"building": True}, dist=300
    )

    assert len(result) == 2
    assert isinstance(result[0], ParcelModel)


def test_get_parcels_with_polygon(mock_ox):
    """Test function to test get parcels from polygon."""
    mock_ox.features_from_polygon.return_value = gpd.GeoDataFrame(
        geometry=[Point(1, 1), Polygon([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]])]
    )

    polygon = [
        GeoLocation(-122.29262, 37.83639),
        GeoLocation(-122.28095, 37.82972),
        GeoLocation(-122.29213, 37.82768),
        GeoLocation(-122.29262, 37.83639),
    ]
    result = parcels_from_location(polygon)
    mock_ox.features_from_polygon.assert_called_once_with(Polygon(polygon), {"building": True})

    assert len(result) == 2
    assert isinstance(result[0], ParcelModel)


def test_osm_mapper_defaults_and_override():
    """OSM mapper uses OSM columns by default and accepts overrides."""
    record = {
        "building": "residential",
        "addr:city": "Boulder",
        "addr:state": "CO",
        "addr:postcode": "80302",
    }
    assert OSMParcelFieldMapper().map_record(record) == {
        "building_type": "residential",
        "city": "Boulder",
        "state": "CO",
        "postal_address": "80302",
    }

    overridden = OSMParcelFieldMapper(column_map={"postal_address": "zip"})
    assert overridden.map_record({"building": "yes", "zip": "80302"})["postal_address"] == "80302"


def test_mapper_rejects_unknown_field():
    """A mapper with an unknown field is rejected early."""
    with pytest.raises(InvalidInputError):
        OSMParcelFieldMapper(column_map={"nonexistent": "building"})


def test_gis_mapper_default_columns():
    """GIS mapper defaults to common FeatureServer column names."""
    assert GISParcelFieldMapper().columns == {
        "building_type": "Building",
        "city": "City",
        "state": "State",
        "postal_address": "Address",
    }


def test_parcels_from_geodataframe_maps_osm_attributes():
    """parcels_from_geodataframe populates the four fields via the mapper."""
    geo_df = gpd.GeoDataFrame(
        {
            "building": ["residential"],
            "addr:city": ["Boulder"],
            "addr:state": ["CO"],
            "addr:postcode": ["80302"],
        },
        geometry=[Polygon([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]])],
        crs="EPSG:4326",
    )
    parcels = parcels_from_geodataframe(geo_df)
    assert len(parcels) == 1
    parcel = parcels[0]
    assert parcel.building_type == "residential"
    assert parcel.city == "Boulder"
    assert parcel.state == "CO"
    assert parcel.postal_address == "80302"


def test_parcels_from_geodataframe_name_column():
    """name_column overrides the default parcel_{index} naming."""
    geo_df = gpd.GeoDataFrame(
        {"OBJECTID": [7]},
        geometry=[Polygon([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]])],
        crs="EPSG:4326",
    )
    parcels = parcels_from_geodataframe(geo_df, name_column="OBJECTID")
    assert parcels[0].name == "7"


_GIS_FEATURE = {
    "geometry": {
        "type": "Polygon",
        "rings": [
            [
                [-105.280, 40.010],
                [-105.270, 40.010],
                [-105.270, 40.020],
                [-105.280, 40.020],
                [-105.280, 40.010],
            ]
        ],
    },
    "attributes": {
        "OBJECTID": 42,
        "Building": "Residential",
        "City": "Boulder",
        "State": "CO",
        "Address": "123 Main St",
    },
}


def _fake_response(payload):
    """Return a minimal object mimicking requests' response."""
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def test_parcels_from_gis_parses_and_maps():
    """parcels_from_gis queries the REST endpoint and maps attributes."""
    with mock.patch("shift.parcel_sources.requests") as mock_requests:
        mock_requests.get.return_value = _fake_response({"features": [_GIS_FEATURE]})
        parcels = parcels_from_gis(
            "https://gis.colorado.gov/public/rest/services/Feeder/FeederServer/0",
            id_field="OBJECTID",
        )

    mock_requests.get.assert_called_once()
    url_arg = mock_requests.get.call_args[0][0]
    assert "FeatureServer/0" in url_arg and "outSR=4326" in url_arg

    assert len(parcels) == 1
    parcel = parcels[0]
    assert parcel.name == "42"
    assert parcel.building_type == "Residential"
    assert parcel.city == "Boulder"
    assert parcel.state == "CO"
    assert parcel.postal_address == "123 Main St"


def test_parcels_from_gis_empty():
    """A layer with no features returns an empty list."""
    with mock.patch("shift.parcel_sources.requests") as mock_requests:
        mock_requests.get.return_value = _fake_response({"features": []})
        parcels = parcels_from_gis(
            "https://gis.colorado.gov/public/rest/services/Feeder/FeederServer/0"
        )
    assert parcels == []


def test_parcels_from_gis_invalid_url():
    """An empty URL is rejected before any network call."""
    with mock.patch("shift.parcel_sources.requests") as mock_requests:
        with pytest.raises(InvalidInputError):
            parcels_from_gis("")
    mock_requests.get.assert_not_called()
