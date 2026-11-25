import json,subprocess,os,hashlib,io,sys,concurrent.futures as cf
from PIL import Image
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
R=json.load(open('crawl/crawl.json'))
only=set(map(int,sys.argv[1:])) if len(sys.argv)>1 else None
def get(args):
    bid,u,a=args
    h=hashlib.md5(u.encode()).hexdigest()[:12]; fn=f'thumbs/{bid}_{h}.jpg'
    try:
        r=subprocess.run(['curl','-sL','-A',UA,'--max-time','25','--max-filesize','16000000',u],capture_output=True)
        b=r.stdout
        im=Image.open(io.BytesIO(b)); W,H=im.size
        if W<500 or H<300 or W/H>3.2 or H/W>1.6: return None
        im=im.convert('RGB'); im.thumbnail((360,240)); im.save(fn,quality=80)
        return dict(id=bid,src=u,alt=a,w=W,h=H,bytes=len(b),thumb=fn,sha=hashlib.md5(b).hexdigest())
    except Exception: return None
jobs=[]
for r in R:
    if only and r['id'] not in only: continue
    for u,a in r["imgs"][:80]: jobs.append((r['id'],u,a))
with cf.ThreadPoolExecutor(24) as ex: out=[x for x in ex.map(get,jobs) if x]
# dedupe by content per building
seen=set();res=[]
for x in out:
    k=(x['id'],x['sha'])
    if k in seen: continue
    seen.add(k);res.append(x)
prev=json.load(open('crawl/cands.json')) if os.path.exists('crawl/cands.json') and only else []
prev=[p for p in prev if p['id'] not in (only or set())]
json.dump(prev+res,open('crawl/cands.json','w'))
from collections import Counter
c=Counter(x['id'] for x in res); print(len(res),'cands;',len(c),'buildings'); print(sorted(c.items()))
