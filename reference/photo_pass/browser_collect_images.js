await new Promise(r=>setTimeout(r,2500));
for(let y=0;y<document.body.scrollHeight;y+=800){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,200))}
await new Promise(r=>setTimeout(r,1200));
const RX=/https?:\/\/[^"'\s<>()\\,]+?\.(?:jpe?g|png|webp|avif)(?:\?[^"'\s<>\\,]*)?|https?:\/\/(?:img\.zumpercdn\.com|images\.myrazz\.com|s7d9\.scene7\.com|photos\.zillowstatic\.com)\/[^"'\s<>\\,]+/gi;
const out=new Map();const add=(u,a)=>{if(!u||u.startsWith('data:'))return;u=u.replace(/&amp;/g,'&');if(!out.has(u)||(!out.get(u)&&a))out.set(u,a||'')};
for(const im of document.images){const u=im.currentSrc||im.src;add(u,im.alt||'');if(im.srcset){const p=im.srcset.split(',').map(s=>s.trim().split(' ')[0]);add(p[p.length-1],im.alt||'')}}
document.querySelectorAll('*').forEach(e=>{const b=getComputedStyle(e).backgroundImage;const m=b&&b.match(/url\("?([^")]+)/);if(m)add(m[1],'')});
(document.documentElement.outerHTML.replace(/\\\//g,'/').match(RX)||[]).forEach(u=>add(u,''));
const links=[...new Set([...document.querySelectorAll('a[href]')].map(a=>a.href.split('#')[0]).filter(h=>h.startsWith(location.origin)&&/galler|photo|tour|media|picture|image|amenit/i.test(h)&&!/\.(jpe?g|png|pdf)$/i.test(h)))].slice(0,5);
for(const l of links){try{const t=await (await fetch(l)).text();(t.replace(/\\\//g,'/').match(RX)||[]).forEach(u=>add(u,''));}catch(e){}}
const imgs=[...out].filter(([u])=>/^https?:/.test(u)&&!/logo|icon|favicon|sprite|badge|marker|avatar|equal-housing|eho|ada[-_.]|social|facebook|instagram|twitter|tiktok|google|yelp|flag|emoji|\.svg/i.test(u));
window.name=JSON.stringify({id:__ID__,url:location.href,links,imgs});
[document.title,imgs.length,links.length]
