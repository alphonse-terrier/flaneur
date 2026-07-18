"""Tests for journey summarization and disruption attachment."""

from flaneur.journeys import _index_disruptions, _summarize_journey, _to_iso

# Minimal but realistic /journeys response, with a disruption attached to one section.
SAMPLE_PAYLOAD = {
    "journeys": [
        {
            "duration": 2671,
            "nb_transfers": 1,
            "type": "best",
            "status": "SIGNIFICANT_DELAYS",
            "departure_date_time": "20260718T120500",
            "arrival_date_time": "20260718T124900",
            "sections": [
                {
                    "type": "street_network",
                    "mode": "walking",
                    "duration": 300,
                    "from": {"name": "Start"},
                    "to": {"name": "Bercy"},
                    "departure_date_time": "20260718T120500",
                    "arrival_date_time": "20260718T121000",
                },
                {
                    "type": "public_transport",
                    "duration": 1260,
                    "from": {"name": "Bercy"},
                    "to": {"name": "Bir-Hakeim"},
                    "departure_date_time": "20260718T121000",
                    "arrival_date_time": "20260718T123100",
                    "display_informations": {
                        "label": "6",
                        "commercial_mode": "Metro",
                        "direction": "Charles de Gaulle — Étoile",
                        "network": "RATP",
                        "links": [{"type": "disruption", "id": "disrupt-1"}],
                    },
                },
            ],
        }
    ],
    "disruptions": [
        {
            "id": "disrupt-1",
            "cause": "roadworks",
            "status": "active",
            "severity": {"name": "disrupted", "effect": "SIGNIFICANT_DELAYS"},
            "application_periods": [{"begin": "20260718T000000", "end": "20260718T235900"}],
            "messages": [{"text": "<p>Roadworks on line 6.</p>"}],
            "impacted_objects": [{"pt_object": {"name": "6", "embedded_type": "line"}}],
        }
    ],
}


def test_to_iso():
    # Navitia local time is stamped as Europe/Paris (tz-aware): summer = +02:00.
    assert _to_iso("20260718T120500") == "2026-07-18T12:05:00+02:00"
    assert _to_iso(None) is None
    assert _to_iso("garbage") == "garbage"


def test_index_disruptions():
    index = _index_disruptions(SAMPLE_PAYLOAD)
    assert "disrupt-1" in index
    disruption = index["disrupt-1"]
    assert disruption.cause == "roadworks"
    assert disruption.effect == "SIGNIFICANT_DELAYS"
    assert disruption.message == "Roadworks on line 6."  # HTML cleaned up
    assert disruption.impacted_objects == ["6"]


def test_summarize_journey_attaches_disruptions():
    index = _index_disruptions(SAMPLE_PAYLOAD)
    journey = _summarize_journey(SAMPLE_PAYLOAD["journeys"][0], index)

    assert journey.duration_minutes == 45  # 2671s ≈ 45 min
    assert journey.nb_transfers == 1
    assert journey.walking_minutes == 5
    assert journey.status == "SIGNIFICANT_DELAYS"
    assert journey.has_disruptions is True

    # 2 sections: walking then metro.
    assert len(journey.sections) == 2
    walk, metro = journey.sections
    assert walk.mode == "street_network"
    assert metro.mode == "public_transport"
    assert metro.line == "6"
    assert metro.direction == "Charles de Gaulle — Étoile"
    assert "Metro 6" in metro.label

    # The disruption is attached to the metro leg, not the walking leg.
    assert not walk.disruptions
    assert len(metro.disruptions) == 1
    assert metro.disruptions[0].cause == "roadworks"


def test_summarize_journey_no_disruptions():
    payload = {
        "journeys": [
            {
                "duration": 600,
                "sections": [
                    {
                        "type": "public_transport",
                        "duration": 600,
                        "display_informations": {"label": "1", "commercial_mode": "Metro"},
                    }
                ],
            }
        ],
        "disruptions": [],
    }
    journey = _summarize_journey(payload["journeys"][0], _index_disruptions(payload))
    assert journey.has_disruptions is False
    assert not journey.sections[0].disruptions
