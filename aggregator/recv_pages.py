"""Localhost receiver for pages collected in the user's own Chrome (Claude in Chrome extension rescues).

Why: the extension's tool output is cut at ~1k characters, and a page on another site cannot reliably post to
localhost. So the page's HTML is put in window.name, the tab navigates to http://127.0.0.1:8767/send?name=<slug>,
and this server's own /send page (same origin, window.name survives the navigation) posts it back in chunks.
Saved to <outdir>/<slug>.html. Then run the normal parser on the saved file, e.g.
  node dom_extract.js entrata_pp file:///<outdir>/<slug>.html '{}'

  python3 recv_pages.py <outdir> [port]
"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8767
parts = {}
SEND = """<!doctype html><title>sending</title><body>sending...<script>
(async () => {
  const name = new URLSearchParams(location.search).get('name');
  const d = window.name || ''; const size = 60000; const n = Math.ceil(d.length / size) || 1;
  for (let i = 0; i < n; i++) {
    await fetch('/chunk?name=' + encodeURIComponent(name) + '&i=' + i + '&n=' + n, {method: 'POST', body: d.slice(i * size, (i + 1) * size)});
  }
  window.name = '';
  document.body.textContent = 'SAVED ' + name + ' ' + d.length + ' chars';
  document.title = 'SAVED ' + name;
})();
</script></body>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(SEND.encode())

    def do_POST(self):
        q = parse_qs(urlparse(self.path).query)
        name, i, n = q["name"][0], int(q["i"][0]), int(q["n"][0])
        body = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8", "replace")
        parts.setdefault(name, {})[i] = body
        if len(parts[name]) == n:
            (OUT / f"{name}.html").write_text("".join(parts[name][k] for k in range(n)))
            print("SAVED", name, flush=True)
            parts.pop(name)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
