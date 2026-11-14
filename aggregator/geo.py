"""Free geocoding + footprint lookup from Overture (addresses = US National Address Database points,
buildings = OSM + ML footprints). Both are openly licensed, so results can be stored forever."""
import json, math, re
from functools import lru_cache
from common import norm_addr, haversine_m


def _feats(cfg, typ):
    seen = set()
    for p in sorted((cfg["dir"] / "cache").glob(f"overture_{typ}_*.geojsonseq")):
        for line in open(p):
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            f = json.loads(line)
            fid = f.get("id") or f["properties"].get("id")
            if fid in seen:
                continue
            seen.add(fid)
            yield f


_ADDR, _BLD = {}, {}


def addr_index(cfg):
    if cfg["slug"] not in _ADDR:
        idx = {}
        for f in _feats(cfg, "address"):
            p = f["properties"]
            if p.get("number") and p.get("street"):
                idx.setdefault(norm_addr(f"{p['number']} {p['street']}"), []).append(
                    (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]))
        _ADDR[cfg["slug"]] = idx
    return _ADDR[cfg["slug"]]


def geocode(cfg, address):
    """address string -> (lat, lng) via NAD address points, or None. Unit numbers are ignored."""
    k = norm_addr(address)
    pts = addr_index(cfg).get(k)
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def _area_centroid(ring, lat0):
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 111320.0
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        X1, Y1, X2, Y2 = x1 * kx, y1 * ky, x2 * kx, y2 * ky
        c = X1 * Y2 - X2 * Y1
        a += c; cx += (X1 + X2) * c; cy += (Y1 + Y2) * c
    if abs(a) < 1e-9:
        return 0.0, (ring[0][1], ring[0][0])
    a *= 0.5
    return abs(a), (cy / (6 * a) / ky, cx / (6 * a) / kx)


def _inside(lat, lng, ring):
    ins = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            ins = not ins
    return ins


def building_index(cfg):
    if cfg["slug"] not in _BLD:
        grid = {}
        for f in _feats(cfg, "building"):
            p = f["properties"]
            for ring in _rings(f["geometry"]):
                area, cen = _area_centroid(ring, ring[0][1])
                if area < 60:
                    continue
                b = {"ring": ring, "area": round(area), "centroid": cen, "floors": p.get("num_floors"),
                     "height": p.get("height"), "name": (p.get("names") or {}).get("primary"),
                     "cls": p.get("class") or p.get("subtype"), "id": f.get("id") or p.get("id")}
                grid.setdefault((round(cen[0], 3), round(cen[1], 3)), []).append(b)
        _BLD[cfg["slug"]] = grid
    return _BLD[cfg["slug"]]


def footprint(cfg, lat, lng, max_m=45):
    """Footprint containing the point, else the nearest centroid within max_m scaled by building size.
    Returns dict(lat, lng, area_m2, floors, height, how, off_m) or None."""
    grid = building_index(cfg)
    best = None
    for dy in (-0.001, 0, 0.001):
        for dx in (-0.001, 0, 0.001):
            for b in grid.get((round(lat + dy, 3), round(lng + dx, 3)), []):
                d = haversine_m(lat, lng, b["centroid"][0], b["centroid"][1])
                ins = _inside(lat, lng, b["ring"])
                reach = max_m + math.sqrt(b["area"]) * 0.5
                if ins or d <= reach:
                    score = (0 if ins else 1, d)
                    if best is None or score < best[0]:
                        best = (score, b, d, ins)
    if not best:
        return None
    _, b, d, ins = best
    return {"lat": round(b["centroid"][0], 6), "lng": round(b["centroid"][1], 6), "area_m2": b["area"],
            "floors": b["floors"], "height": b["height"], "footprint_name": b["name"], "footprint_class": b["cls"],
            "how": "pin_inside_footprint" if ins else "nearest_footprint", "off_m": round(d), "footprint_id": b["id"]}
