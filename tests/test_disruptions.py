"""Tests for disruption parsing and real-time departures."""

from flaneur.departures import (
    _navitia_id_to_monitoring_ref,
    _parse_visits,
    _short_line,
)
from flaneur.disruptions import _clean_text, _extract_disruptions, parse_disruption


def test_clean_text_strips_html():
    assert _clean_text("<p>Roadworks <b>line 6</b></p>") == "Roadworks line 6"
    assert _clean_text(None) is None
    assert _clean_text("") is None


def test_parse_disruption():
    raw = {
        "id": "abc",
        "cause": "incident",
        "status": "active",
        "severity": {"name": "blocking", "effect": "NO_SERVICE"},
        "application_periods": [{"begin": "20260718T080000", "end": "20260718T100000"}],
        "messages": [{"text": "Service interrupted."}],
        "impacted_objects": [{"pt_object": {"name": "RER A"}}],
    }
    d = parse_disruption(raw)
    assert d.id == "abc"
    assert d.cause == "incident"
    assert d.effect == "NO_SERVICE"
    assert d.severity == "blocking"
    assert d.begin == "2026-07-18T08:00:00"
    assert d.end == "2026-07-18T10:00:00"
    assert d.message == "Service interrupted."
    assert d.impacted_objects == ["RER A"]


def test_extract_disruptions_navitia_format():
    payload = {"disruptions": [{"id": "x", "severity": {"effect": "DETOUR"}}]}
    result = _extract_disruptions(payload)
    assert len(result) == 1
    assert result[0].effect == "DETOUR"


def test_extract_disruptions_empty():
    assert _extract_disruptions({}) == []
    assert _extract_disruptions(None) == []


def test_navitia_id_to_monitoring_ref():
    assert (
        _navitia_id_to_monitoring_ref("stop_area:IDFM:71517")
        == "STIF:StopArea:SP:71517:"
    )
    assert (
        _navitia_id_to_monitoring_ref("STIF:StopArea:SP:71517:")
        == "STIF:StopArea:SP:71517:"
    )
    assert _navitia_id_to_monitoring_ref("") is None
    assert _navitia_id_to_monitoring_ref("stop_area:IDFM:abc") is None


def test_short_line():
    assert _short_line("STIF:Line::C01371:") == "C01371"
    assert _short_line(None) is None


def test_parse_visits():
    payload = {
        "Siri": {
            "ServiceDelivery": {
                "StopMonitoringDelivery": [
                    {
                        "MonitoredStopVisit": [
                            {
                                "MonitoredVehicleJourney": {
                                    "LineRef": {"value": "STIF:Line::C01742:"},
                                    "DestinationName": [{"value": "La Défense"}],
                                    "MonitoredCall": {
                                        "ExpectedDepartureTime": "2026-07-18T12:10:00Z",
                                        "AimedDepartureTime": "2026-07-18T12:08:00Z",
                                        "DepartureStatus": "delayed",
                                    },
                                }
                            }
                        ]
                    }
                ]
            }
        }
    }
    departures = _parse_visits(payload)
    assert len(departures) == 1
    dep = departures[0]
    assert dep.line == "C01742"
    assert dep.destination == "La Défense"
    assert dep.expected == "2026-07-18T12:10:00Z"
    assert dep.status == "delayed"


def test_parse_visits_empty():
    assert _parse_visits({}) == []
    assert _parse_visits({"Siri": {}}) == []
