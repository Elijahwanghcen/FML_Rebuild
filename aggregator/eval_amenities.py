"""Phase C: compare rebuilt amenities with the legacy UT amenities_features.json (per building + overall)."""
import json, sys
from collections import Counter
from common import campus
from enrich_site import slugify
cfg = campus(sys.argv[1])
old = {f["property_name"]: {t for L in f["features"].values() for t in L} for f in json.load(open(sys.argv[2]))}
tp = fp = fn = 0
ev = Counter(); miss = Counter(); extra = Counter(); rows = []
for b in json.load(open(cfg["dir"] / "roster_test.json")):
    p = cfg["dir"] / "raw" / slugify(b["canonical_name"]) / "amenities.json"
    if not p.exists():
        rows.append((b["truth_name"], "NO DATA", "", "", "")); continue
    new = json.load(open(p)); mine = set(new["amenities"]); o = old[b["truth_name"]]
    tp += len(mine & o); fp += len(mine - o); fn += len(o - mine)
    miss.update(o - mine); extra.update(mine - o)
    ev.update(v["evidence_type"] + "/" + v["method"] for v in new["amenities"].values())
    rows.append((b["truth_name"], len(o), len(mine), len(mine & o), ",".join(new["pages_read"])))
for r in rows: print("%-26s old=%-3s new=%-3s both=%-3s %s" % r)
print(f"\nrecall of old terms={tp/(tp+fn):.0%}  share of new terms also in old={tp/(tp+fp):.0%}  new-only terms={fp}")
print("evidence:", dict(ev)); print("most missed:", miss.most_common(8)); print("most added:", extra.most_common(8))
