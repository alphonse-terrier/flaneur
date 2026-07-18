"""Geocoding parsing tests (no network calls)."""

from flaneur.geocoding import _parse_geocoder_feature, _parse_lonlat, _parse_navitia_place


def test_parse_lonlat_valid():
    loc = _parse_lonlat("2.3378;48.8606")
    assert loc is not None
    assert loc.longitude == 2.3378
    assert loc.latitude == 48.8606
    assert loc.lonlat == "2.3378;48.8606"


def test_parse_lonlat_invalid():
    assert _parse_lonlat("Eiffel Tower") is None
    assert _parse_lonlat("2.3378,48.8606") is None


def test_parse_geocoder_feature():
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [2.062821, 49.031624]},
                "properties": {
                    "label": "8 Boulevard du Port 95000 Cergy",
                    "type": "housenumber",
                    "city": "Cergy",
                    "postcode": "95000",
                },
            }
        ],
    }
    loc = _parse_geocoder_feature(data)
    assert loc is not None
    assert loc.longitude == 2.062821
    assert loc.latitude == 49.031624
    assert loc.city == "Cergy"
    assert loc.postcode == "95000"
    assert loc.lonlat == "2.062821;49.031624"


def test_parse_geocoder_feature_empty():
    assert _parse_geocoder_feature({"features": []}) is None


def test_parse_navitia_place():
    place = {
        "embedded_type": "stop_area",
        "name": "Châtelet",
        "id": "stop_area:IDFM:71517",
        "stop_area": {"coord": {"lon": "2.3470", "lat": "48.8583"}},
    }
    loc = _parse_navitia_place(place)
    assert loc is not None
    assert loc.longitude == 2.3470
    assert loc.latitude == 48.8583
    assert loc.label == "Châtelet"
    assert loc.kind == "stop_area"
