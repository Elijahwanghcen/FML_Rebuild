import json
from PIL import Image
C=json.load(open('crawl/cands.json'));keep=[]
for c in C:
    im=Image.open(c['thumb']).convert('L').resize((90,60)); px=list(im.getdata())
    ext=sum(1 for p in px if p>235 or p<20)/len(px)
    c['ext']=round(ext,2)
    if ext<0.5: keep.append(c)
json.dump(keep,open('crawl/cands.json','w')); print(len(C),'->',len(keep))
