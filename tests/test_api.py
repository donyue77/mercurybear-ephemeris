import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mercurybear_ephemeris import core
from mercurybear_ephemeris.app import SOURCE_URL, app

c = TestClient(app)
REF = json.loads((Path(__file__).parent / "reference.json").read_text())["cases"]
needs_files = pytest.mark.skipif(core.EPHEMERIS != "swiss", reason="reference values use the Swiss Ephemeris data files")


@needs_files
@pytest.mark.parametrize("case", REF, ids=[x["case"] for x in REF])
def test_reference_positions_and_cusps(case):
    r = c.post("/v1/chart", json=case["request"]).json()
    exp = case["expect"]
    for name, (lon, lat, speed) in exp["bodies"].items():
        b = r["bodies"][name]
        assert abs(b["lon"] - lon) <= 1e-9 and abs(b["lat"] - lat) <= 1e-9 and abs(b["speed_lon"] - speed) <= 1e-9, name
    h = r["houses"][case["request"]["house_systems"][0]]
    assert h["used"] == exp["used"]
    assert all(abs(a - b) <= 1e-9 for a, b in zip(h["cusps"], exp["cusps"]))
    assert abs(r["asc"] - exp["asc"]) <= 1e-9 and abs(r["mc"] - exp["mc"]) <= 1e-9


def test_source_header_and_link():
    r = c.get("/v1/health")
    assert r.status_code == 200 and r.headers["X-Source-Code"] == SOURCE_URL
    assert c.get("/source").json()["license"] == "AGPL-3.0-only"


@pytest.mark.parametrize("local,offset,dst", [("1950-07-15T10:00", 9.0, 1.0), ("1975-07-01T09:30", 9.0, 1.0), ("1980-07-01T09:30", 8.0, 0.0)])
def test_taiwan_daylight_saving_time(local, offset, dst):
    r = c.post("/v1/time", json={"local": local, "timezone": "Asia/Taipei"}).json()
    assert (r["utc_offset_hours"], r["dst_offset_hours"]) == (offset, dst)
    assert r["utc"].startswith(f"{local[:11]}{int(local[11:13]) - int(offset):02d}:{local[14:16]}")


def test_polar_house_fallback():
    r = c.post("/v1/chart", json={"utc": "1980-01-05T11:00:00Z", "lat": 69.65, "lon": 18.95, "house_systems": ["P"]}).json()
    assert r["houses"]["P"]["used"] == "O" and "failed" in r["houses"]["P"] and r["warnings"]
    r = c.post("/v1/chart", json={"utc": "1980-01-05T11:00:00Z", "lat": 69.65, "lon": 18.95, "house_systems": ["P"], "fallback": None}).json()
    assert "error" in r["houses"]["P"]


@needs_files
def test_events_2026():
    r = c.post("/v1/events", json={"start": "2026-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z", "eclipses": True,
                                   "sun_crossings": [0], "stations": ["mercury"]}).json()
    ecl = [(e["kind"], core.revjul(e["jd"])[:3], e["type"]) for e in r["eclipses"]]
    assert ("solar_eclipse", (2026, 2, 17), "annular") in ecl and ("solar_eclipse", (2026, 8, 12), "total") in ecl
    assert ("lunar_eclipse", (2026, 3, 3), "total") in ecl and ("lunar_eclipse", (2026, 8, 28), "partial") in ecl
    equinox = r["sun_crossings"][0]["jd"]
    assert abs(equinox - core.julday(2026, 3, 20, 14 + 46 / 60)) * 1440 < 1.0          # 2026-03-20 14:46 UT
    assert len([s for s in r["stations"] if s["direction"] == "retrograde"]) == 3        # Mercury turns retrograde three times


@needs_files
def test_lunations_and_search_agree():
    r = c.post("/v1/events", json={"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z", "lunations": True}).json()
    new = next(e for e in r["lunations"] if e["kind"] == "new_moon")
    assert abs(new["jd"] - core.julday(2026, 10, 10, 15 + 50 / 60)) * 1440 < 2
    s = c.post("/v1/search", json={"jobs": [{"fn": {"type": "separation", "a": "moon", "b": "sun"}, "start": new["jd"] - 1,
                                             "end": new["jd"] + 1, "step": 0.1, "guard": 20}],
                                   "syzygy": [{"before": new["jd"] + 3}]}).json()
    assert abs(s["results"][0]["roots"][0] - new["jd"]) * 1440 < 1
    assert s["syzygy"][0]["kind"] == "new_moon" and abs(s["syzygy"][0]["jd"] - new["jd"]) * 1440 < 1


def test_positions_batch_and_errors():
    r = c.post("/v1/positions", json={"jd_ut": [2451545.0, 2451546.0], "bodies": ["sun", "mars"]}).json()
    assert len(r["positions"]["sun"]) == 2 and len(r["positions"]["sun"][0]) == 6
    assert c.post("/v1/positions", json={"jd_ut": [2451545.0], "bodies": ["vulcan"]}).status_code == 422
