"""Download the Swiss Ephemeris data files (planets, moon, main asteroids 1800-2400, fixed stars).

    mercurybear-ephemeris-fetch [DEST]      # default: $SE_EPHE_PATH or ./ephe

Files come from the Astrodienst repository on GitHub and are checked against known SHA-256 sums.
They are never committed to this repository.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request

BASE = "https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/"
FILES = {
    "sepl_18.se1": "ca1393ceab3a44fbc895887cf789c68819ae6a1cbc9b22225872dbe4ccd99a66",
    "semo_18.se1": "1ca07bd67c24374d77226180c20a4f9996cba013697894810518e7eb582ca4f7",
    "seas_18.se1": "a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2",
    "sefstars.txt": "18b0dcafbe5b7240773daba2c038a325f5b3fc4163f61e0a7f4e92abd4f517c6",
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    for name, digest in FILES.items():
        path = os.path.join(dest, name)
        if os.path.exists(path) and sha256(path) == digest:
            print(f"ok       {name}")
            continue
        tmp = path + ".part"
        urllib.request.urlretrieve(BASE + name, tmp)
        got = sha256(tmp)
        if got != digest:
            os.remove(tmp)
            raise SystemExit(f"checksum mismatch for {name}: {got}")
        os.replace(tmp, path)
        print(f"fetched  {name}")


def main() -> None:
    fetch(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SE_EPHE_PATH") or os.path.join(os.getcwd(), "ephe"))


if __name__ == "__main__":
    main()
