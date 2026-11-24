"""Build data/open-data.json for data.html from the City of Berkeley open data portal.

Downloads 311 cases, restaurant inspections, council district boundaries and parcels,
works out which council district each record is in, and writes one compact JSON file.
Run: python3 scripts/build_open_data.py   (needs pandas and shapely)
"""
import json, re, io, urllib.request, datetime as dt
import pandas as pd
from shapely.geometry import shape, Point, mapping
from shapely.prepared import prep

PORTAL = "https://data.cityofberkeley.info"
SINCE = "2025-12-01"   # 311 data is near-complete from December 2025 on
OUT = "data/open-data.json"

def get(path):
    with urllib.request.urlopen(PORTAL + path, timeout=300) as r:
        return r.read()

def meta(dataset_id):
    m = json.loads(get(f"/api/views/{dataset_id}.json"))
    t = m.get("rowsUpdatedAt") or m.get("viewLastModified")
    return {"name": m["name"], "id": dataset_id, "url": f"{PORTAL}/d/{dataset_id}",
            "updated": dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d") if t else None}

# Council districts
dist_geo = json.loads(get("/resource/c8zs-8y7x.geojson"))
shapes = {f["properties"]["district"]: shape(f["geometry"]) for f in dist_geo["features"]}
prepared = {k: prep(v) for k, v in shapes.items()}

def district(lat, lon):
    if pd.isna(lat) or pd.isna(lon):
        return 0
    p = Point(lon, lat)
    for k, s in prepared.items():
        if s.contains(p):
            return int(k)
    return 0

def rounded(geom):
    def r(c):
        if isinstance(c[0], (float, int)):
            return [round(c[0], 5), round(c[1], 5)]
        return [r(x) for x in c]
    g = mapping(geom.simplify(0.00008, preserve_topology=True))
    return {"type": g["type"], "coordinates": r(json.loads(json.dumps(g["coordinates"])))}

outlines = [{"district": int(k), "geometry": rounded(v)} for k, v in sorted(shapes.items(), key=lambda x: int(x[0]))]

# 311 cases
c311 = pd.read_csv(io.BytesIO(get("/resource/p88g-6gs2.csv?$limit=200000")),
                   parse_dates=["date_opened", "date_closed"])
c311 = c311[c311.date_opened >= SINCE].copy()
c311["district"] = [district(a, b) for a, b in zip(c311.latitude, c311.longitude)]
types = c311.case_request.value_counts().index.tolist()
statuses = ["Closed", "Open", "In Progress", "On Hold"]
start = pd.Timestamp(SINCE)
rows = []
for r in c311.itertuples():
    close = (r.date_closed - r.date_opened).days if pd.notna(r.date_closed) and r.case_status == "Closed" else -1
    rows.append([(r.date_opened - start).days, types.index(r.case_request),
                 statuses.index(r.case_status) if r.case_status in statuses else 1,
                 r.district, close, round(r.latitude, 4), round(r.longitude, 4)])

# Address -> coordinates, from parcels and geocoded 311 addresses, for restaurant addresses
NUM = {'1ST':'FIRST','2ND':'SECOND','3RD':'THIRD','4TH':'FOURTH','5TH':'FIFTH','6TH':'SIXTH','7TH':'SEVENTH','8TH':'EIGHTH','9TH':'NINTH','10TH':'TENTH'}
SUF = {'AVENUE':'AVE','AV':'AVE','STREET':'ST','WY':'WAY','PLACE':'PL','ROAD':'RD','DRIVE':'DR','COURT':'CT','LANE':'LN'}
def norm_street(s):
    s = str(s).upper().replace('.', '').replace(',', ' ')
    s = re.sub(r'\b(MLK JR|MARTIN LUTHER KING JR|MARTIN LUTHER KING|M L KING JR|MLK)\b', 'MARTIN LUTHER KING JR', s)
    w = [SUF.get(x, x) for x in (NUM.get(x, x) for x in s.split())]
    out = []
    for x in w:
        if x in ('UNIT', 'STE', 'SUITE') or x.startswith('#'):
            break
        out.append(x)
    if len(out) > 1 and re.fullmatch(r'[A-Z]|\d+[A-Z]?', out[-1]) and out[-2] in ('AVE','ST','WAY','PL','RD','BLVD','DR','CT','LN'):
        out = out[:-1]
    return ' '.join(out)

points = {}
parcels = json.loads(get("/resource/rax9-nuvx.geojson?$limit=100000"))
for f in parcels["features"]:
    p = f["properties"]
    try:
        points.setdefault(norm_street(p["situs_str_1"]), []).append((int(p["situs_stree"]), float(p["latitude"]), float(p["longitude"])))
    except (TypeError, ValueError, KeyError):
        pass
all311 = pd.read_csv(io.BytesIO(get("/resource/p88g-6gs2.csv?$select=street_address,latitude,longitude&$limit=200000")))
for a, la, lo in zip(all311.street_address, all311.latitude, all311.longitude):
    m = re.match(r'(\d+)\s+(.*)', str(a))
    if m and pd.notna(la):
        points.setdefault(norm_street(m.group(2)), []).append((int(m.group(1)), la, lo))

FIX = {'UNIVESITY':'UNIVERSITY','UNIVERSTIY':'UNIVERSITY','UNIVERSIIY':'UNIVERSITY','TELEGRPH':'TELEGRAPH','TELGRAPH':'TELEGRAPH',
       'DURANT ST':'DURANT AVE','ADELINE AVE':'ADELINE ST','SACRAMENTO AVE':'SACRAMENTO ST','KALA BAGAI AVE':'KALA BAGAI WAY',
       ' M L KING':' MLK','DOMINGO ST':'DOMINGO AVE'}
def geocode(addr):
    a = str(addr).upper().split(',')[0].strip()
    for k, v in FIX.items():
        a = a.replace(k, v)
    a = re.sub(r'\s+(STE|FL|BLDG|SW)\b.*$', '', a)
    m = re.match(r'(\d+)(?:-\d+|-?[A-Z])?\s+(?:[A-Z]\s+)?(.*)', a)
    if not m:
        return None
    n, L = int(m.group(1)), points.get(norm_street(m.group(2)))
    if not L:
        return None
    same = [x for x in L if x[0] % 2 == n % 2]
    best = min(same, key=lambda x: abs(x[0] - n)) if same else None
    if best is None or abs(best[0] - n) > 60:
        best = min(L, key=lambda x: abs(x[0] - n))
        if abs(best[0] - n) > 60:
            return None
    return best[1], best[2]

# Restaurant inspections: one facility per name + address, latest inspection
ri = pd.read_csv(io.BytesIO(get("/resource/izax-e46a.csv?$limit=50000")), parse_dates=["inspection_date"])
flag_cols = [c for c in ri.columns if c.startswith(("major_", "minor_"))]
ri["addr"] = ri.restaurant_address.str.replace(r",\s*BERKELEY, CA\s*$", "", regex=True).str.strip()
def nice(s):
    """Title-case a name or address without capitalizing after apostrophes (Andronico's, not Andronico'S)."""
    return re.sub(r"[A-Za-z]+('[A-Za-z]+)?", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), s.strip())

facilities = []
for (name, addr), g in ri.groupby(["doing_business_as", "addr"], sort=True):
    latest = g.inspection_date.max()
    at = g[g.inspection_date == latest] if pd.notna(latest) else g
    flags = [c for c in flag_cols if (at[c].fillna(0).astype(int) > 0).any()]
    ll = geocode(g.restaurant_address.iloc[0])
    facilities.append({"n": nice(name), "a": nice(addr),
                       "d": latest.strftime("%Y-%m-%d") if pd.notna(latest) else None,
                       "major": [c.replace("major_violation_", "") for c in flags if c.startswith("major")],
                       "minor": [c.replace("minor_violation_", "") for c in flags if c.startswith("minor")],
                       "dist": district(*ll) if ll else 0})

out = {
    "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "sources": {"311": meta("p88g-6gs2"), "restaurants": meta("izax-e46a"), "districts": meta("c8zs-8y7x")},
    "districts": outlines,
    "c311": {"since": SINCE, "types": types, "statuses": statuses,
             "fields": ["day", "type", "status", "district", "daysToClose", "lat", "lon"], "rows": rows},
    "restaurants": facilities,
}
with open(OUT, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote {OUT}: {len(rows)} 311 cases, {len(facilities)} facilities, "
      f"{sum(1 for x in facilities if not x['dist'])} without a district")
