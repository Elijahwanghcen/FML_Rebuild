"""Localhost receiver for data collected inside the user's own browser (for sites that block scripts, e.g.
Akamai-fronted campus directories). The page sends chunks as GET /?i=<idx>&n=<total>&d=<urlencoded text>;
when all chunks are in, the joined text is written to <outfile>.   python3 recv_local.py <outfile> [port]"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
out, port = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 8766
parts = {}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        if "d" in q:
            parts[int(q["i"][0])] = q["d"][0]
            n = int(q["n"][0])
            print("chunk", q["i"][0], "of", n, flush=True)
            if len(parts) == n:
                open(out, "w").write("".join(parts[i] for i in range(n)))
                print("WROTE", out, flush=True)
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
HTTPServer.request_queue_size = 64
HTTPServer(("127.0.0.1", port), H).serve_forever()
