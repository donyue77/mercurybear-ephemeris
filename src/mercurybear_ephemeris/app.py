"""HTTP API (JSON). Numbers only: positions, cusps, times and event instants."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from . import __version__, core

SOURCE_URL = "https://github.com/donyue77/mercurybear-ephemeris"

app = FastAPI(title="mercurybear-ephemeris", version=__version__,
              description="Astronomical calculation service built on the Swiss Ephemeris. AGPL-3.0. Source: " + SOURCE_URL)


@app.middleware("http")
async def source_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Source-Code"] = SOURCE_URL
    return response


@app.exception_handler(core.CalcError)
async def calc_error(_request: Request, exc: core.CalcError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _jd(jd_ut: float | None, utc: str | None) -> float:
    if jd_ut is not None:
        return jd_ut
    if utc is None:
        raise core.CalcError("give jd_ut or utc")
    t = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    t = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    return core.julday(t.year, t.month, t.day, t.hour + t.minute / 60 + t.second / 3600 + t.microsecond / 3.6e9)


# ------------------------------------------------------------------ meta
@app.get("/v1/health")
def health():
    return {"status": "ok", "version": __version__, "swisseph": swe.version, "ephemeris": core.EPHEMERIS}


@app.get("/source")
def source():
    return {"source": SOURCE_URL, "license": "AGPL-3.0-only", "version": __version__}


# ------------------------------------------------------------------ time
class TimeIn(BaseModel):
    local: str | None = Field(None, examples=["1975-07-01T09:30"], description="local civil time, with `timezone`")
    timezone: str | None = Field(None, examples=["Asia/Taipei"], description="IANA zone name")
    fold: Literal[0, 1] = 0
    utc: str | None = None
    jd_ut: float | None = None


@app.post("/v1/time")
def time(b: TimeIn):
    offset = dst = None
    if b.local is not None:
        if not b.timezone:
            raise core.CalcError("local time needs an IANA timezone")
        try:
            tz = ZoneInfo(b.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise core.CalcError(f"unknown timezone '{b.timezone}'") from None
        aware = datetime.fromisoformat(b.local).replace(tzinfo=tz, fold=b.fold)
        offset, dst = aware.utcoffset(), aware.dst()
        utc = aware.astimezone(timezone.utc)
        jd = core.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60 + utc.second / 3600 + utc.microsecond / 3.6e9)
    else:
        jd = _jd(b.jd_ut, b.utc)
    y, m, d, h = core.revjul(jd)
    secs = round(h * 3600, 3)
    dt = core.deltat(jd)
    return {"jd_ut": jd, "utc": f"{y:04d}-{m:02d}-{d:02d}T{int(secs // 3600):02d}:{int(secs % 3600 // 60):02d}:{secs % 60:06.3f}Z",
            "utc_offset_hours": offset.total_seconds() / 3600 if offset is not None else None,
            "dst_offset_hours": dst.total_seconds() / 3600 if dst is not None else None,
            "delta_t": dt, "delta_t_sec": dt * 86400, "jd_tt": jd + dt}


# ------------------------------------------------------------------ chart
DEFAULT_BODIES = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]


class ChartIn(BaseModel):
    utc: str | None = Field(None, examples=["1991-04-05T11:30:00Z"])
    jd_ut: float | None = None
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    bodies: list[str] = DEFAULT_BODIES
    house_systems: list[str] = ["P"]
    fallback: str | None = Field("O", description="house system used when a requested one fails (polar latitudes); null = no fallback")
    fixed_stars: list[str] = []


def _body_out(jd: float, name: str) -> dict:
    try:
        xx = core.calc(jd, name)
        eq = core.calc(jd, name, core.FLAGS | swe.FLG_EQUATORIAL)
    except swe.Error as e:
        return {"error": str(e)}
    return {"lon": xx[0], "lat": xx[1], "dist": xx[2], "speed_lon": xx[3], "speed_lat": xx[4], "speed_dist": xx[5],
            "ra": eq[0], "dec": eq[1]}


@app.post("/v1/chart")
def chart(b: ChartIn):
    jd = _jd(b.jd_ut, b.utc)
    bodies = {name: _body_out(jd, name) for name in dict.fromkeys(b.bodies)}
    houses, warnings, angles = {}, [], None
    for s in dict.fromkeys(b.house_systems):
        h = core.houses(jd, b.lat, b.lon, s)
        h["requested"], h["used"] = s, s
        if "error" in h and b.fallback:
            err = h["error"]
            h = core.houses(jd, b.lat, b.lon, b.fallback) | {"requested": s, "used": b.fallback, "failed": err}
            warnings.append(f"house system {s} failed ({err}); used {b.fallback}")
        houses[s] = h
        if angles is None and "ascmc" in h:
            a = h["ascmc"]
            angles = {"asc": a[0], "mc": a[1], "armc": a[2], "vertex": a[3]}
    if angles is None:
        warnings.append("no house system could be computed; angles unavailable")
    obl = core.obliquity(jd)
    out = {"jd_ut": jd, "delta_t_sec": core.deltat(jd) * 86400, "ephemeris": core.EPHEMERIS,
           "obliquity": obl["true"], "mean_obliquity": obl["mean"], "bodies": bodies, "houses": houses, "warnings": warnings,
           **(angles or {})}
    sun = bodies.get("sun") or _body_out(jd, "sun")
    if "error" not in sun:
        out["sun_altitude"] = core.altitude(jd, b.lat, b.lon, sun["lon"], sun["lat"])
    if b.fixed_stars:
        out["fixed_stars"] = {name: core.fixed_star(name, jd) for name in dict.fromkeys(b.fixed_stars)}
    return out


# ------------------------------------------------------------------ batch positions
class PositionsIn(BaseModel):
    jd_ut: list[float] = Field(..., max_length=20000)
    bodies: list[str]
    equatorial: bool = False


@app.post("/v1/positions")
def positions(b: PositionsIn):
    """Positions of several bodies at many instants: [lon, lat, dist, speed_lon, speed_lat, speed_dist] per instant."""
    fl = core.FLAGS | (swe.FLG_EQUATORIAL if b.equatorial else 0)
    out, errors = {}, {}
    for name in dict.fromkeys(b.bodies):
        try:
            out[name] = [list(core.calc(t, name, fl)) for t in b.jd_ut]
        except swe.Error as e:
            errors[name] = str(e)
    return {"ephemeris": core.EPHEMERIS, "positions": out, "errors": errors}


# ------------------------------------------------------------------ events
class Range(BaseModel):
    start_jd: float | None = None
    end_jd: float | None = None
    start: str | None = None
    end: str | None = None

    def bounds(self) -> tuple[float, float]:
        return _jd(self.start_jd, self.start), _jd(self.end_jd, self.end)


class EventsIn(Range):
    lunations: bool = False
    eclipses: bool = False
    ingresses: list[str] = []
    stations: list[str] = []
    aspects_exact: list[str] = Field([], description="bodies; every pair is searched")
    angles: list[int] = list(core.ANGLES)
    sun_crossings: list[float] = Field([], description="ecliptic longitudes; first instant after start when the Sun reaches each")
    eclipse_before: float | None = Field(None, description="JD: also return the last solar and lunar eclipse before this instant")
    eclipse_before_moshier: bool = False

    @model_validator(mode="after")
    def _angles(self):
        if any(a not in core.ANGLES for a in self.angles):
            raise ValueError(f"angles must be among {core.ANGLES}")
        return self


@app.post("/v1/events")
def events(b: EventsIn):
    needs_range = b.lunations or b.eclipses or b.ingresses or b.stations or b.aspects_exact or b.sun_crossings
    out: dict = {}
    if needs_range:
        j0, j1 = b.bounds()
        if b.lunations:
            out["lunations"] = core.lunations(j0, j1)
        if b.eclipses:
            out["eclipses"] = core.eclipses(j0, j1)
        if b.ingresses:
            out["ingresses"] = core.ingresses(j0, j1, b.ingresses)
        if b.stations:
            out["stations"] = core.stations(j0, j1, b.stations)
        if b.aspects_exact:
            out["aspects_exact"] = core.aspects_exact(j0, j1, b.aspects_exact, tuple(b.angles))
        if b.sun_crossings:
            out["sun_crossings"] = [{"lon": L, "jd": core.sun_crossing(L, j0)} for L in b.sun_crossings]
    if b.eclipse_before is not None:
        out["eclipse_before"] = {k: core.eclipse_before(b.eclipse_before, k, b.eclipse_before_moshier) for k in ("solar", "lunar")}
    return out


# ------------------------------------------------------------------ generic searches
class Fn(BaseModel):
    type: Literal["separation", "speed"]
    a: str
    b: str | None = None
    lon: float | None = None
    offset: float = 0.0


class SearchJob(BaseModel):
    id: str | int | None = None
    fn: Fn
    start: float
    step: float
    end: float | None = None
    max_steps: int | None = Field(None, le=1_000_000)
    guard: float | None = None
    first: bool = False
    tol: float = core.MINUTE / 4


class SyzygyJob(BaseModel):
    id: str | int | None = None
    before: float


class SearchIn(BaseModel):
    jobs: list[SearchJob] = Field([], max_length=5000)
    syzygy: list[SyzygyJob] = Field([], max_length=1000)


@app.post("/v1/search")
def search(b: SearchIn):
    """Sample-and-bisect root finding.

    separation: f(t) = diff180(lon_a(t) - X - offset), X = lon_b(t) or a fixed `lon`.
    speed:      f(t) = longitude speed of a.
    """
    out = []
    for j in b.jobs:
        f = core.separation_fn(j.fn.a, j.fn.b, j.fn.lon, j.fn.offset) if j.fn.type == "separation" else core.speed_fn(j.fn.a)
        core.body_id(j.fn.a)
        roots = core.scan(f, j.start, j.step, end=j.end, max_steps=j.max_steps, guard=j.guard, first=j.first, tol=j.tol)
        out.append({"id": j.id, "roots": roots})
    return {"results": out, "syzygy": [{"id": s.id, **core.syzygy_before(s.before)} for s in b.syzygy]}
