// WITHDRAWN 2026-11-18: do not run. Listing aggregators (Zumper, Zillow, Apartments.com, RentCollegePads, campus directories)
// are never a photo, rent or amenity source. Kept only as a record of how the first A&M photo pass worked.
// Run in the page of a listing-site BUILDING page (tested on Zumper) through the browser tool.
// Replace __ID__ with the building's id, then navigate the tab to http://127.0.0.1:8777/recv.
//
// A listing page carries photos of nearby listings too. The building's own set is the "media" list
// that starts with the page's main (og:image) photo. Do not use any other id list on the page.
await new Promise(r=>setTimeout(r,2500));
const og=(document.querySelector('meta[property="og:image"]')||{}).content||'';
const first=(og.match(/com\/(\d+)/)||[])[1];
const t=[...document.scripts].map(s=>s.textContent).join('\n');
const i=first?t.indexOf('"media":[{"media_id":'+first):-1;
const seg=i<0?'':t.slice(i,i+20000);
const ids=[...seg.slice(0,seg.indexOf(']')).matchAll(/"media_id":(\d+)/g)].map(m=>m[1]);
const h1=(document.querySelector('h1')||{}).textContent||'';
window.name=JSON.stringify({id:__ID__,url:location.href,links:[h1],imgs:ids.map(x=>['https://img.zumpercdn.com/'+x+'/1280x960',''])});
// Check before trusting: location.href is still the building page (a redirect to a city search means
// the page no longer exists) and h1 shows the building's name or street address.
[location.href,h1,ids.length]
