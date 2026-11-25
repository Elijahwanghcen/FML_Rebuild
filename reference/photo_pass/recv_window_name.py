import json,os
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
D=sys.argv[1] if len(sys.argv)>1 else 'browser_out'   # folder the page data is written to
PAGE=b"""<html><body><pre id=s>sending</pre><script>
const d=window.name; fetch('/save',{method:'POST',body:d}).then(r=>r.text()).then(t=>{document.getElementById('s').textContent='saved '+t;document.title='saved '+t;window.name=''});
</script></body></html>"""
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(PAGE)
    def do_POST(self):
        b=self.rfile.read(int(self.headers['Content-Length'])).decode()
        try:
            j=json.loads(b); fn=f"{D}/{j['id']}.json"
            prev=json.load(open(fn)) if os.path.exists(fn) else {'id':j['id'],'pages':[],'imgs':[]}
            prev['pages'].append(j.get('url')); prev['imgs']+=j.get('imgs',[])
            json.dump(prev,open(fn,'w')); msg=f"{j['id']} {len(j.get('imgs',[]))}"
        except Exception as e: msg='ERR '+str(e)[:80]
        print(msg,flush=True)
        self.send_response(200);self.end_headers();self.wfile.write(msg.encode())
    def log_message(self,*a):pass
os.makedirs(D,exist_ok=True)
HTTPServer(('127.0.0.1',8777),H).serve_forever()
