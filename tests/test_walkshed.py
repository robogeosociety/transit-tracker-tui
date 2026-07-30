"""Tests for walkshed notebook logic — validates GTFS loading, OSMnx walkshed
computation, and GeoJSON output structure."""

import csv
import json
from pathlib import Path

import networkx as nx
import pytest
from osmnx import convert, distance, graph
from shapely.geometry import MultiPoint, mapping
from shapely.ops import unary_union

PROJECT_ROOT = Path(__file__).parent.parent
GTFS_DIR = PROJECT_ROOT / "data" / "gtfs"

TARGET_ROUTES = {"100479", "2LINE"}
WALK_SPEED_M_PER_MIN = 75
CONTOUR_MINUTES = [5, 10, 15]


# ---------------------------------------------------------------------------
# GTFS station loading (same logic as notebook cell 1)
# ---------------------------------------------------------------------------


def load_stations(gtfs_dir: Path) -> list[dict]:
    trips_path = gtfs_dir / "40" / "trips.txt"
    stop_times_path = gtfs_dir / "40" / "stop_times.txt"
    stops_path = gtfs_dir / "40" / "stops.txt"
    for p in [trips_path, stop_times_path, stops_path]:
        if not p.exists():
            pytest.skip(f"{p} not found — run scripts/download_gtfs.py first")

    with open(trips_path) as f:
        trip_ids = {
            t["trip_id"] for t in csv.DictReader(f) if t["route_id"] in TARGET_ROUTES
        }
    with open(stop_times_path) as f:
        stop_ids = {r["stop_id"] for r in csv.DictReader(f) if r["trip_id"] in trip_ids}

    seen: set[str] = set()
    stations = []
    with open(stops_path) as f:
        for s in csv.DictReader(f):
            if s["stop_id"] in stop_ids and s["stop_name"] not in seen:
                seen.add(s["stop_name"])
                stations.append(
                    {
                        "name": s["stop_name"],
                        "lat": float(s["stop_lat"]),
                        "lon": float(s["stop_lon"]),
                    }
                )
    return sorted(stations, key=lambda s: s["name"])


class TestLoadStations:
    def test_returns_nonempty(self):
        stations = load_stations(GTFS_DIR)
        assert len(stations) > 0, "Expected at least one light rail station"

    def test_stations_have_required_fields(self):
        stations = load_stations(GTFS_DIR)
        for s in stations:
            assert "name" in s and isinstance(s["name"], str) and s["name"]
            assert "lat" in s and isinstance(s["lat"], float)
            assert "lon" in s and isinstance(s["lon"], float)

    def test_stations_are_sorted_by_name(self):
        stations = load_stations(GTFS_DIR)
        names = [s["name"] for s in stations]
        assert names == sorted(names)

    def test_stations_are_deduplicated(self):
        stations = load_stations(GTFS_DIR)
        names = [s["name"] for s in stations]
        assert len(names) == len(set(names)), "Duplicate station names found"

    def test_coordinates_in_puget_sound_region(self):
        stations = load_stations(GTFS_DIR)
        for s in stations:
            assert 47.0 < s["lat"] < 48.0, f"{s['name']} lat {s['lat']} out of range"
            assert -123.0 < s["lon"] < -122.0, (
                f"{s['name']} lon {s['lon']} out of range"
            )

    def test_known_stations_present(self):
        stations = load_stations(GTFS_DIR)
        names = {s["name"] for s in stations}
        for expected in ["Westlake", "U District", "Capitol Hill"]:
            assert any(expected in n for n in names), (
                f"Expected station containing '{expected}'"
            )


# ---------------------------------------------------------------------------
# OSMnx walkshed computation (same logic as notebook cell 2)
# ---------------------------------------------------------------------------


def compute_walksheds(
    lat: float, lon: float, contour_minutes: list[int] = CONTOUR_MINUTES
) -> list[dict]:
    max_dist = max(contour_minutes) * WALK_SPEED_M_PER_MIN * 1.4
    G = graph.graph_from_point((lat, lon), dist=max_dist, network_type="walk")
    distance.add_edge_lengths(G)
    center = distance.nearest_nodes(G, lon, lat)

    results = []
    for minutes in sorted(contour_minutes, reverse=True):
        radius_m = minutes * WALK_SPEED_M_PER_MIN
        subgraph = nx.ego_graph(G, center, radius=radius_m, distance="length")
        nodes_gdf = convert.graph_to_gdfs(subgraph, edges=False)
        points = MultiPoint(list(nodes_gdf.geometry))
        walkshed = unary_union(points.buffer(0.0012))
        # mapping() returns tuples; normalize to lists for JSON compat
        geom = json.loads(json.dumps(mapping(walkshed)))
        results.append(
            {
                "minutes": minutes,
                "geometry": geom,
            }
        )
    return results


@pytest.mark.network
class TestComputeWalksheds:
    """Tests that hit the Overpass API — marked 'network' so CI can skip them."""

    # Use Capitol Hill station as a single test point
    TEST_LAT, TEST_LON = 47.6163, -122.3209

    @pytest.fixture(scope="class")
    def walksheds(self):
        return compute_walksheds(self.TEST_LAT, self.TEST_LON)

    def test_returns_one_entry_per_contour(self, walksheds):
        assert len(walksheds) == len(CONTOUR_MINUTES)

    def test_each_entry_has_minutes_and_geometry(self, walksheds):
        for ws in walksheds:
            assert "minutes" in ws
            assert "geometry" in ws
            assert ws["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_contour_minutes_match(self, walksheds):
        returned = sorted(ws["minutes"] for ws in walksheds)
        assert returned == sorted(CONTOUR_MINUTES)

    def test_larger_contours_have_more_area(self, walksheds):
        from shapely.geometry import shape

        areas = {ws["minutes"]: shape(ws["geometry"]).area for ws in walksheds}
        assert areas[5] < areas[10] < areas[15], (
            f"Areas not monotonically increasing: {areas}"
        )

    def test_geometry_is_json_serializable(self, walksheds):
        for ws in walksheds:
            parsed = json.loads(json.dumps(ws["geometry"]))
            assert parsed["type"] in ("Polygon", "MultiPolygon")
            assert len(parsed["coordinates"]) > 0

    def test_walkshed_contains_origin(self, walksheds):
        from shapely.geometry import Point, shape

        origin = Point(self.TEST_LON, self.TEST_LAT)
        for ws in walksheds:
            poly = shape(ws["geometry"])
            assert poly.contains(origin), (
                f"{ws['minutes']}-min walkshed doesn't contain origin"
            )


# ---------------------------------------------------------------------------
# GeoJSON output structure
# ---------------------------------------------------------------------------


class TestGeoJSONStructure:
    """Validate the output GeoJSON shape that the Leaflet map expects."""

    @staticmethod
    def make_feature(name: str, lon: float, lat: float, walksheds: list[dict]) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "walksheds": walksheds},
        }

    def test_feature_collection_structure(self):
        feature = self.make_feature(
            "Test Station",
            -122.33,
            47.6,
            [
                {
                    "minutes": 5,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                },
            ],
        )
        fc = {"type": "FeatureCollection", "features": [feature]}
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 1
        assert fc["features"][0]["geometry"]["type"] == "Point"

    def test_walkshed_property_format(self):
        walksheds = [
            {"minutes": 5, "geometry": {"type": "Polygon", "coordinates": []}},
            {"minutes": 10, "geometry": {"type": "Polygon", "coordinates": []}},
            {"minutes": 15, "geometry": {"type": "Polygon", "coordinates": []}},
        ]
        feature = self.make_feature("Test", -122.0, 47.0, walksheds)
        ws = feature["properties"]["walksheds"]
        assert len(ws) == 3
        assert [w["minutes"] for w in ws] == [5, 10, 15]
        assert all(w["geometry"]["type"] == "Polygon" for w in ws)

    def test_leaflet_compat_old_format_fallback(self):
        """The notebook handles the old single-walkshed format too."""
        old_feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.33, 47.6]},
            "properties": {
                "name": "Old Station",
                "walkshed": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                },
            },
        }
        props = old_feature["properties"]
        walksheds = props.get("walksheds") or []
        if not walksheds and "walkshed" in props:
            walksheds = [{"minutes": 10, "geometry": props["walkshed"]}]
        assert len(walksheds) == 1
        assert walksheds[0]["minutes"] == 10

    def test_roundtrip_json_serializable(self):
        feature = self.make_feature(
            "Roundtrip",
            -122.33,
            47.6,
            [
                {
                    "minutes": 10,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                },
            ],
        )
        fc = {"type": "FeatureCollection", "features": [feature]}
        serialized = json.dumps(fc)
        parsed = json.loads(serialized)
        assert parsed == fc
