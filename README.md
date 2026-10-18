# mercurybear-ephemeris

A small HTTP service for astronomical calculations, built on the
[Swiss Ephemeris](https://www.astro.com/swisseph/). It returns numbers only:
positions of planets and points, house cusps, time-scale conversions and the
instants of astronomical events. It makes no astrological judgements.

It runs as a separate process next to the Mercury Bear applications, which call
it over HTTP/JSON. Every response carries an `X-Source-Code` header pointing to
this repository, and `GET /source` returns the same link.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/chart` | Positions (ecliptic and equatorial) of the requested bodies, house cusps for one or more house systems (with an optional fallback system at polar latitudes), ASC/MC/ARMC/Vertex, true obliquity, Sun altitude, optional fixed stars |
| `POST /v1/positions` | Positions of several bodies at many instants in one request |
| `POST /v1/time` | Local civil time + IANA zone → UTC, applied UTC offset (historical daylight saving time included), Julian day, Delta T |
| `POST /v1/events` | New and full moons, solar and lunar eclipses, sign ingresses, stations, exact separations of 0/60/90/120/180 degrees between pairs, Sun reaching a given longitude, last eclipses before an instant |
| `POST /v1/search` | Sample-and-bisect root finding for a separation (body vs. body or a fixed longitude) or for a speed change; last new or full moon before an instant |
| `GET /v1/health`, `GET /source` | Status and source link |

Bodies: `sun moon mercury venus mars jupiter saturn uranus neptune pluto
true_node mean_node mean_lilith chiron ceres pallas juno vesta`.
House systems: Swiss Ephemeris one-letter codes (`P` Placidus, `W` whole sign,
`B` Alcabitius, `R` Regiomontanus, `K` Koch, `O` Porphyry, `A` equal, `C` Campanus, ...).
Times are given either as `jd_ut` (Julian day, UT) or ISO `utc` strings.
Interactive documentation is served at `/docs`.

```bash
curl -s localhost:8100/v1/chart -H 'content-type: application/json' \
  -d '{"utc":"1991-04-05T11:30:00Z","lat":25.033,"lon":121.565,"house_systems":["P","W"]}'
```

## Running

```bash
pip install git+https://github.com/donyue77/mercurybear-ephemeris@v0.1.0
mercurybear-ephemeris-fetch ./ephe          # downloads and checksums the data files
SE_EPHE_PATH=./ephe mercurybear-ephemeris    # listens on 127.0.0.1:8100 (CALC_HOST / CALC_PORT)
```

The data files (`sepl_18.se1`, `semo_18.se1`, `seas_18.se1` for 1800–2400, and
`sefstars.txt`) are downloaded from the Astrodienst repository at build time and
are not stored here. Without them the service falls back to the Moshier analytical
ephemeris and reports `"ephemeris": "moshier"`.

## Tests

```bash
pip install -e ".[test]" && mercurybear-ephemeris-fetch ephe
SE_EPHE_PATH=$PWD/ephe pytest -q
python scripts/content_check.py
```

`tests/reference.json` holds reference values for 20 instants and places
(southern hemisphere, polar latitude, before 1900, after 2050, historical
daylight saving time, a Sun on the horizon).

## License

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License, version 3 (see `LICENSE`).
If you run a modified version as a network service, you must offer its source
code to the users of that service.

The Swiss Ephemeris is © Astrodienst AG, Zurich, Switzerland, and is used under
the GNU Affero General Public License; see the
[Swiss Ephemeris license](https://www.astro.com/swisseph/swephinfo_e.htm#_Toc46391649).
The ephemeris data files are © Astrodienst AG.
