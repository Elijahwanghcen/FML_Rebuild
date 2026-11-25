import json,re,html,subprocess,sys,os,hashlib,concurrent.futures as cf
from urllib.parse import urljoin,urlparse
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BAD=re.compile(r'logo|icon|favicon|sprite|badge|marker|pin\b|avatar|eho|equal-housing|ada|accessib|wheelchair|placeholder|blank|spinner|loader|arrow|button|social|facebook|instagram|twitter|tiktok|google|yelp|payment|qr|banner-ad|cookie|1x1|pixel|map|floor|plan|layout|siteplan|\.svg|\.gif|ajax|emoji|flag|partner|award',re.I)
def fetch(url,timeout=25):
    r=subprocess.run(['curl','-sL','-A',UA,'--compressed','--max-time',str(timeout),'-w','\n%{http_code} %{url_effective}',url],capture_output=True)
    body=r.stdout.decode('utf-8','ignore'); body,_,tail=body.rpartition('\n')
    code,_,eff=tail.partition(' ')
    return code,eff,body
def imgs(page,base):
    s=html.unescape(page).replace('\\/','/')
    out=[]
    # img tags with alt
    for m in re.finditer(r'<img\b[^>]*>',s,re.I):
        tag=m.group(0)
        alt=(re.search(r'\balt\s*=\s*"([^"]*)"',tag) or re.search(r"\balt\s*=\s*'([^']*)'",tag))
        alt=alt.group(1) if alt else ''
        cands=[]
        for a in ['data-src','data-lazy-src','data-original','src']:
            v=re.search(r'\b'+a+r'\s*=\s*"([^"]+)"',tag)
            if v: cands.append(v.group(1))
        ss=re.search(r'\b(?:data-)?srcset\s*=\s*"([^"]+)"',tag)
        if ss:
            parts=[p.strip().split(' ') for p in ss.group(1).split(',') if p.strip()]
            def w(p):
                try: return int(p[1].rstrip('w')) if len(p)>1 and p[1].endswith('w') else 0
                except: return 0
            parts.sort(key=w)
            if parts: cands.insert(0,parts[-1][0])
        for c in cands:
            if c.startswith('data:'): continue
            out.append((urljoin(base,c),alt)); break
    # background images + raw urls
    for m in re.finditer(r'(?:https?:)?//[^"\'\s<>()\\,]+?\.(?:jpe?g|png|webp)(?:\?[^"\'\s<>\\,]*)?',s,re.I):
        out.append((urljoin(base,m.group(0)),''))
    for m in re.finditer(r'url\(\s*[\'"]?([^\'")]+\.(?:jpe?g|png|webp)[^\'")]*)',s,re.I):
        out.append((urljoin(base,m.group(1)),''))
    seen={};res=[]
    for u,a in out:
        if not u.startswith('http'): continue
        if BAD.search(urlparse(u).path) or BAD.search(a or ''): continue
        key=re.sub(r'-\d+x\d+(?=\.\w+$)','',u.split('?')[0])
        if key in seen:
            if a and not res[seen[key]][1]: res[seen[key]]=(res[seen[key]][0],a)
            continue
        seen[key]=len(res);res.append((u,a))
    return res
def links(page,base):
    s=html.unescape(page)
    host=urlparse(base).netloc
    L=[]
    for h in re.findall(r'href\s*=\s*"([^"#]+)"',s,re.I):
        u=urljoin(base,h)
        if urlparse(u).netloc==host and re.search(r'galler|photo|amenit|tour|interior|community|features',u,re.I) and not re.search(r'\.(pdf|jpg|png)$',u,re.I): L.append(u)
    return list(dict.fromkeys(L))[:4]
def crawl(t):
    w=t['website']; res={'id':t['id'],'pages':[],'imgs':[]}
    if not w: return res
    code,eff,body=fetch(w)
    res['pages'].append((w,code,eff,len(body)))
    if code!='200': return res
    allimgs=imgs(body,eff)
    for u in links(body,eff)+[urljoin(eff,'/gallery'),urljoin(eff,'/photos')]:
        if any(u==p[0] for p in res['pages']): continue
        c,e,b=fetch(u,20); res['pages'].append((u,c,e,len(b)))
        if c=='200': allimgs+= imgs(b,e)
    d={};[d.setdefault(u,a) for u,a in allimgs]
    res['imgs']=list(d.items())
    return res
T=json.load(open('targets.json'))
only=set(map(int,sys.argv[1:])) if len(sys.argv)>1 else None
T=[t for t in T if not only or t['id'] in only]
with cf.ThreadPoolExecutor(12) as ex:
    R=list(ex.map(crawl,T))
json.dump(R,open('crawl/crawl.json','w'))
for t,r in zip(T,R):
    print(t['id'],t['name'][:28],'|',(r['pages'][0][1] if r['pages'] else 'nosite'),'|',len(r['imgs']),'imgs')
