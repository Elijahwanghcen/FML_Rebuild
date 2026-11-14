"""Source 5: Reddit. Students name the buildings they actually live in (and their nicknames).
Input: cache/reddit_corpus.json from reddit_fetch.js (needs a user-logged-in browser).
1. LLM pulls every housing building name out of each thread.
2. Names are counted per thread (mention count = student-relevance signal).
3. Names not already known are looked up one at a time with Places Text Search (biased to campus).
Outputs: reddit_mentions.json (name -> threads, variants) and cand_reddit.json (located candidates)."""
import json, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from common import campus, norm_name, name_sim, haversine_m, places_post, places_spend
from llm import ask_json

FM = "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.primaryType,places.websiteUri,places.userRatingCount"


def extract(cfg, post):
    text = (post.get("title", "") + "\n" + (post.get("body") or "") + "\n" + "\n".join(post.get("comments") or []))[:24000]
    if len(text) < 80:
        return []
    r = ask_json(
        f"Below is a Reddit thread from r/{post.get('sub')} about housing near {cfg['name']} ({cfg['city']}, {cfg['state']}).\n"
        f"List every specific apartment complex, condo building, housing co-op or private dorm that is named, as students "
        f"wrote it (keep nicknames like 'Rio West', 'the Callaway House', '26 West'). Do NOT list neighbourhoods, streets, "
        f"management companies, on-campus university dorms, or generic words.\n"
        f"Return a JSON array of objects: name, sentiment (positive|negative|mixed|neutral), "
        f"note (<=12 words: the main thing said about it).\n\n{text}")
    return [x for x in (r or []) if isinstance(x, dict) and x.get("name")]


def main(slug):
    cfg = campus(slug)
    cw = set(cfg.get("city_words", []))
    corpus = json.load(open(cfg["dir"] / "cache" / "reddit_corpus.json"))
    posts = [p for p in corpus if p.get("comments") is not None]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda p: extract(cfg, p), posts))
    groups = []           # [norm, {variants}, {thread ids}, [notes]]
    for p, items in zip(posts, res):
        for it in items:
            n = norm_name(it["name"], cw)
            if len(n) < 3:
                continue
            g = next((g for g in groups if name_sim(g[0], n) >= 90), None)
            if not g:
                g = [n, defaultdict(int), set(), []]
                groups.append(g)
            g[1][it["name"].strip()] += 1
            g[2].add(p["id"])
            g[3].append({"s": it.get("sentiment"), "note": it.get("note"), "thread": p["id"]})
    ment = sorted(({"name": max(g[1], key=g[1].get), "variants": dict(g[1]), "threads": len(g[2]), "notes": g[3][:8]}
                   for g in groups), key=lambda x: -x["threads"])
    (cfg["dir"] / "reddit_mentions.json").write_text(json.dumps(ment, indent=1))
    # locate the ones other sources do not already have
    known = []
    for fn in ("cand_places.json", "cand_rcp.json", "cand_overture.json"):
        f = cfg["dir"] / fn
        known += [norm_name(x["name"], cw) for x in (json.load(open(f)) if f.exists() else []) if x.get("name")]
    cands, lookups = [], 0
    for m in ment:
        n = norm_name(m["name"], cw)
        if any(name_sim(n, k) >= 90 for k in known):
            continue
        if m["threads"] < 2 or places_spend(cfg) > 30:
            continue
        lookups += 1
        r = places_post(cfg, "searchText", {"textQuery": f"{m['name']} apartments, {cfg['city']}, {cfg['state']}",
                                            "locationBias": {"circle": {"center": {"latitude": cfg["center"][0], "longitude": cfg["center"][1]},
                                                                        "radius": 15000.0}}, "pageSize": 3}, FM)
        for p in r.get("places", [])[:1]:
            loc = p["location"]
            d = haversine_m(cfg["center"][0], cfg["center"][1], loc["latitude"], loc["longitude"])
            s = name_sim(n, norm_name(p["displayName"]["text"], cw))
            if d <= cfg["max_radius_m"] and s >= 60:
                cands.append({"name": p["displayName"]["text"], "address": p.get("formattedAddress"), "lat": loc["latitude"],
                              "lng": loc["longitude"], "type": "", "url": p.get("websiteUri"), "place_id": p["id"],
                              "reddit_name": m["name"], "threads": m["threads"], "sources": ["reddit"]})
    (cfg["dir"] / "cand_reddit.json").write_text(json.dumps(cands, indent=1))
    print(f"threads={len(posts)} distinct names={len(ment)} >=2 threads={sum(1 for m in ment if m['threads']>=2)} "
          f"new lookups={lookups} located={len(cands)}")


if __name__ == "__main__":
    main(sys.argv[1])
