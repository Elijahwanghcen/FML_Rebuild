import json,sys
from PIL import Image,ImageDraw,ImageFont
C=json.load(open('crawl/cands.json')); T={t['id']:t for t in json.load(open('targets.json'))}
ids=[int(x) for x in sys.argv[2:]] if len(sys.argv)>2 else sorted({c['id'] for c in C})
N=int(sys.argv[1]) if len(sys.argv)>1 else 8
try: F=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',22); f2=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',26)
except: F=f2=ImageFont.load_default()
idx={}
G=2; groups=[ids[i:i+G] for i in range(0,len(ids),G)]
for gi,g in enumerate(groups):
    rows=[]
    for bid in g:
        cs=[c for c in C if c['id']==bid][:N]
        idx[bid]=[c['src'] for c in cs]
        h=36+((len(cs)+3)//4)*244
        im=Image.new('RGB',(1448,h),'white'); d=ImageDraw.Draw(im)
        d.text((6,4),f"{bid} {T[bid]['name']}  —  {T[bid]['website']}",fill='black',font=f2)
        for i,c in enumerate(cs):
            t=Image.open(c['thumb']); x=(i%4)*362; y=36+(i//4)*244
            im.paste(t,(x,y)); d.rectangle([x,y,x+30,y+28],fill='yellow'); d.text((x+6,y+2),str(i),fill='black',font=F)
        rows.append(im)
    H=sum(r.height for r in rows)+10*len(rows)
    out=Image.new('RGB',(1448,H),(90,90,90)); y=0
    for r in rows: out.paste(r,(0,y)); y+=r.height+10
    out.save(f'sheets/s{gi:02d}.jpg',quality=82)
json.dump(idx,open('sheets/idx.json','w'))
print(len(groups),'sheets')
