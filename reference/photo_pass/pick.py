import json,sys,os
# usage: pick.py BID "i:caption" ...   (indices refer to current sheets/idx.json)
idx=json.load(open('sheets/idx.json')); P=json.load(open('picks.json')) if os.path.exists('picks.json') else {}
bid=sys.argv[1]; L=P.get(bid,[])
for a in sys.argv[2:]:
    i,cap=a.split(':',1); src=idx[bid][int(i)]
    if src not in [x['src'] for x in L]: L.append({'src':src,'title':cap})
P[bid]=L; json.dump(P,open('picks.json','w'),indent=1); print(bid,len(L))
