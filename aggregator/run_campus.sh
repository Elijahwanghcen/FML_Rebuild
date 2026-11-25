#!/bin/zsh
# Full pipeline for one campus after the user-assisted collections (campus directory via Chrome, Reddit login) are done.
# usage: ./run_campus.sh <campus> [topN]
set -u
C=$1; N=${2:-170}
cd "$(dirname "$0")"
python3 discover_pm_sites.py $C
python3 resolve_addresses.py $C
python3 discover_reddit.py $C
python3 merge_candidates.py $C
python3 select_roster.py $C
python3 apply_resolutions.py $C roster_final.json      # hand-verified identities: data/<campus>/resolutions.json
python3 -c "
import json,sys
from common import campus
d=campus('$C')['dir']; f=json.load(open(d/'roster_final.json')); json.dump(f[:$N],open(d/'roster_enrich.json','w'),indent=1); print('enrich',len(f[:$N]))"
python3 enrich_site.py $C roster_enrich.json
python3 enrich_amenities.py $C roster_enrich.json
python3 enrich_listings.py $C roster_enrich.json
python3 build_json.py $C roster_enrich.json
