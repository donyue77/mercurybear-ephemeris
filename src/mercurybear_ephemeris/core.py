"""Astronomical computations on top of the Swiss Ephemeris.

Everything here is pure astronomy: time scales, positions of planets and points,
house cusps, the horizon, fixed stars and the instants of astronomical events.
No astrological judgement lives in this package.

The search routines (sign ingresses, stations, exact angular separations,
syzygies) sample a function on a fixed step and refine sign changes by
bisection. Step sizes, guards and tolerances are parameters so that callers
get reproducible instants.
"""
from __future__ import annotations

import os
from functools import lru_cache

import swisseph as swe

# ------------------------------------------------------------------ ephemeris files
EPHE_PATH = os.environ.get("SE_EPHE_PATH") or os.path.join(os.getcwd(), "ephe")
_HAS_FILES = os.path.isdir(EPHE_PATH) and any(f.endswith(".se1") for f in os.listdir(EPHE_PATH))
if os.path.isdir(EPHE_PATH):
    swe.set_ephe_path(EPHE_PATH)

#: flags used for every position unless a request asks otherwise
FLAGS = (swe.FLG_SWIEPH if _HAS_FILES else swe.FLG_MOSEPH) | swe.FLG_SPEED
EPHEMERIS = "swiss" if _HAS_FILES else "moshier"

BODIES = {
    "sun": swe.SUN, "moon": swe.MOON, "mercury": swe.MERCURY, "venus": swe.VENUS, "mars": swe.MARS,
    "jupiter": swe.JUPITER, "saturn": swe.SATURN, "uranus": swe.URANUS, "neptune": swe.NEPTUNE, "pluto": swe.PLUTO,
    "true_node": swe.TRUE_NODE, "mean_node": swe.MEAN_NODE, "mean_lilith": swe.MEAN_APOG,
    "chiron": swe.CHIRON, "ceres": swe.CERES, "pallas": swe.PALLAS, "juno": swe.JUNO, "vesta": swe.VESTA,
}
HOUSE_SYSTEMS = set("PKORCAEWBMTUVXHGYNIiLQS")
MINUTE = 1 / 1440


class CalcError(ValueError):
    pass


def body_id(name: str) -> int:
    try:
        return BODIES[name]
    except KeyError:
        raise CalcError(f"unknown body '{name}'; known: {sorted(BODIES)}") from None


# ------------------------------------------------------------------ time
def julday(year: int, month: int, day: int, hour: float) -> float:
    return swe.julday(year, month, day, hour, swe.GREG_CAL)


def revjul(jd: float) -> tuple[int, int, int, float]:
    return swe.revjul(jd, swe.GREG_CAL)


def deltat(jd_ut: float) -> float:
    """Delta T in days."""
    return swe.deltat(jd_ut)


# ------------------------------------------------------------------ positions
def calc(jd_ut: float, name: str, flags: int = FLAGS) -> tuple[float, ...]:
    """(lon, lat, dist, speed_lon, speed_lat, speed_dist); equatorial when flags include FLG_EQUATORIAL."""
    xx, _ = swe.calc_ut(jd_ut, body_id(name), flags)
    return tuple(xx)


@lru_cache(maxsize=200_000)
def lon_speed(jd_ut: float, name: str) -> tuple[float, float]:
    """Ecliptic longitude normalised to [0, 360) and longitude speed (deg/day)."""
    xx = calc(jd_ut, name)
    return norm360(xx[0]), xx[3]


def norm360(x: float) -> float:
    x = x % 360.0
    return x + 360.0 if x < 0 else x


def diff180(x: float) -> float:
    """Signed angle in (-180, 180]."""
    return (x + 180) % 360 - 180


def obliquity(jd_ut: float) -> dict:
    xx, _ = swe.calc_ut(jd_ut, swe.ECL_NUT)
    return {"true": xx[0], "mean": xx[1], "nutation_lon": xx[2], "nutation_obl": xx[3]}


def houses(jd_ut: float, lat: float, lon: float, system: str) -> dict:
    if system not in HOUSE_SYSTEMS:
        raise CalcError(f"unknown house system '{system}'")
    try:
        cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, system.encode())
    except swe.Error as e:
        return {"error": str(e)}
    return {"cusps": list(cusps[:12]), "ascmc": list(ascmc)}


def altitude(jd_ut: float, lat: float, lon: float, ecl_lon: float, ecl_lat: float) -> float:
    """True altitude above the horizon of an ecliptic position (no refraction, sea level)."""
    return swe.azalt(jd_ut, swe.ECL2HOR, (lon, lat, 0), 0, 0, (ecl_lon, ecl_lat, 1))[1]


def fixed_star(name: str, jd_ut: float) -> dict:
    try:
        xx, full, _ = swe.fixstar2_ut(name, jd_ut)
        mag = swe.fixstar2_mag(name)[0]
    except swe.Error as e:
        return {"error": str(e)}
    return {"name": full, "lon": xx[0], "lat": xx[1], "dist": xx[2], "mag": mag}


# ------------------------------------------------------------------ searching
def bisect(f, a: float, b: float, tol: float = MINUTE / 4) -> float:
    fa = f(a)
    for _ in range(60):
        if b - a <= tol:
            break
        m = (a + b) / 2
        fm = f(m)
        if (fm > 0) == (fa > 0):
            a, fa = m, fm
        else:
            b = m
    return (a + b) / 2


def separation_fn(a: str, b: str | None = None, lon: float | None = None, offset: float = 0.0):
    """f(t) = diff180(lon_a(t) - X - offset) with X = lon_b(t), or a fixed longitude."""
    if b is not None:
        return lambda t: diff180(lon_speed(t, a)[0] - lon_speed(t, b)[0] - offset)
    if lon is None:
        raise CalcError("separation needs a second body or a fixed longitude")
    return lambda t: diff180(lon_speed(t, a)[0] - lon - offset)


def speed_fn(a: str):
    return lambda t: lon_speed(t, a)[1]


def scan(f, start: float, step: float, end: float | None = None, max_steps: int | None = None,
         guard: float | None = None, first: bool = False, tol: float = MINUTE / 4) -> list[float]:
    """Sample f from `start` and bisect every sign change.

    Bounded (end given): walk forward to `end`, clamping the last step.
    Unbounded (max_steps given): walk `max_steps` steps of `step` (may be negative) and stop at the first root.
    `guard` ignores sign changes where |f| is not below the guard on both sides (wrap-around at ±180).
    """
    ok = (lambda u, v: True) if guard is None else (lambda u, v: abs(u) < guard and abs(v) < guard)
    roots: list[float] = []
    t, fv = start, f(start)
    if end is not None:
        while t < end:
            t2 = min(t + step, end)
            f2 = f(t2)
            if (fv > 0) != (f2 > 0) and ok(fv, f2):
                roots.append(bisect(f, t, t2, tol))
                if first:
                    break
            t, fv = t2, f2
        return roots
    if max_steps is None:
        raise CalcError("scan needs either end or max_steps")
    for _ in range(max_steps):
        t2 = t + step
        f2 = f(t2)
        if (fv > 0) != (f2 > 0) and ok(fv, f2):
            lo, hi = sorted((t, t2))
            return [bisect(f, lo, hi, tol)]
        t, fv = t2, f2
    return roots


def sign_index(lon: float) -> int:
    return int(norm360(lon) // 30)


def ingresses(start: float, end: float, bodies: list[str]) -> list[dict]:
    """Instants when bodies change zodiac sign (30-degree segment of ecliptic longitude)."""
    out = []
    for p in bodies:
        step = 0.25 if p == "moon" else 1.0
        t, s = start, sign_index(lon_speed(start, p)[0])
        while t < end:
            t2 = min(t + step, end)
            s2 = sign_index(lon_speed(t2, p)[0])
            if s2 != s:
                boundary = (s2 * 30) if (s2 - s) % 12 == 1 else (s * 30)
                jd = bisect(lambda x: diff180(lon_speed(x, p)[0] - boundary), t, t2)
                L, v = lon_speed(jd, p)
                out.append({"jd": jd, "body": p, "from_sign": s, "to_sign": s2, "lon": L, "speed": v})
            t, s = t2, s2
    return out


def stations(start: float, end: float, bodies: list[str]) -> list[dict]:
    """Instants when the longitude speed of a body changes sign."""
    out = []
    for p in bodies:
        t, v = start, lon_speed(start, p)[1]
        while t < end:
            t2 = min(t + 1.0, end)
            v2 = lon_speed(t2, p)[1]
            if (v > 0) != (v2 > 0):
                jd = bisect(speed_fn(p), t, t2)
                out.append({"jd": jd, "body": p, "direction": "retrograde" if v > 0 else "direct", "lon": lon_speed(jd, p)[0]})
            t, v = t2, v2
    return out


ANGLES = (0, 60, 90, 120, 180)


def aspects_exact(start: float, end: float, bodies: list[str], angles=ANGLES) -> list[dict]:
    """Instants of exact angular separation (0/60/90/120/180) between pairs of bodies."""
    out = []
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            step = 0.1 if "moon" in (a, b) else 0.5
            for ang in angles:
                for sgn in ((1,) if ang in (0, 180) else (1, -1)):
                    for jd in scan(separation_fn(a, b, offset=sgn * ang), start, step, end=end, guard=20):
                        La, va = lon_speed(jd, a)
                        Lb, vb = lon_speed(jd, b)
                        out.append({"jd": jd, "a": a, "b": b, "angle": ang, "direction": sgn,
                                    "a_lon": La, "a_speed": va, "b_lon": Lb, "b_speed": vb})
    return out


def lunations(start: float, end: float) -> list[dict]:
    """New and full moons (exact Sun-Moon conjunction and opposition)."""
    return [{"jd": e["jd"], "kind": "new_moon" if e["angle"] == 0 else "full_moon", "moon_lon": e["b_lon"], "sun_lon": e["a_lon"]}
            for e in aspects_exact(start, end, ["sun", "moon"], (0, 180))]


ECL_TYPES = [(swe.ECL_TOTAL, "total"), (swe.ECL_ANNULAR, "annular"), (swe.ECL_PARTIAL, "partial"), (swe.ECL_PENUMBRAL, "penumbral")]


def eclipse_type(flag: int) -> str:
    if hasattr(swe, "ECL_ANNULAR_TOTAL") and flag & swe.ECL_ANNULAR_TOTAL == swe.ECL_ANNULAR_TOTAL:
        return "hybrid"
    for bit, k in ECL_TYPES:
        if flag & bit:
            return k
    return "unknown"


def _eclipse(kind: str, jd: float, flag: int) -> dict:
    sun, moon = lon_speed(jd, "sun")[0], lon_speed(jd, "moon")[0]
    nn = norm360(calc(jd, "true_node")[0])
    near = "north" if abs(diff180(sun - nn)) <= 90 else "south"
    return {"jd": jd, "kind": kind, "type": eclipse_type(flag), "flags": flag, "sun_lon": sun, "moon_lon": moon, "node": near}


def eclipses(start: float, end: float, kinds=("solar", "lunar")) -> list[dict]:
    """Solar and lunar eclipses with maximum in [start, end]."""
    out = []
    if "solar" in kinds:
        t = start
        while True:
            flag, tret = swe.sol_eclipse_when_glob(t, FLAGS, 0, False)[:2]
            if tret[0] > end or tret[0] <= 0:
                break
            out.append(_eclipse("solar_eclipse", tret[0], flag))
            t = tret[0] + 20
    if "lunar" in kinds:
        t = start
        while True:
            flag, tret = swe.lun_eclipse_when(t, FLAGS, 0, False)[:2]
            if tret[0] > end or tret[0] <= 0:
                break
            out.append(_eclipse("lunar_eclipse", tret[0], flag))
            t = tret[0] + 20
    return out


def eclipse_before(jd: float, kind: str, moshier: bool = False) -> dict | None:
    """The last solar or lunar eclipse before jd."""
    fl = swe.FLG_MOSEPH if moshier else FLAGS
    try:
        if kind == "solar":
            flag, tret = swe.sol_eclipse_when_glob(jd, fl, 0, True)[:2]
            return _eclipse("solar_eclipse", tret[0], flag)
        flag, tret = swe.lun_eclipse_when(jd, fl, 0, True)[:2]
        return _eclipse("lunar_eclipse", tret[0], flag)
    except swe.Error:
        return None


def sun_crossing(lon: float, start: float) -> float:
    """First instant after `start` when the Sun reaches the given ecliptic longitude."""
    return swe.solcross_ut(lon, start, FLAGS)


def syzygy_before(jd: float) -> dict:
    """The last new or full moon before jd (whichever came last)."""
    def elong(t):
        return (lon_speed(t, "moon")[0] - lon_speed(t, "sun")[0]) % 360

    e0 = elong(jd)
    target = 0.0 if e0 < 180 else 180.0
    back = ((e0 - target) % 360) / 12.19
    lo, hi = jd - back - 1.5, jd
    f = lambda t: ((elong(t) - target + 180) % 360) - 180
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    t = (lo + hi) / 2
    return {"jd": t, "kind": "new_moon" if target == 0 else "full_moon", "moon_lon": lon_speed(t, "moon")[0]}
