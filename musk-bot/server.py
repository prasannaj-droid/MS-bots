#!/usr/bin/env python3
"""Local HTTP endpoint that accepts Teams-shaped activities.

  python server.py            # http://localhost:3978
  open http://localhost:3978  # a tiny fake Teams chat to try it in the browser
  curl -s localhost:3978/api/messages -H 'content-type: application/json' -d @samples/activity_mention.json

Prototype only: it answers inline in the HTTP response and does NOT validate the
Bot Framework JWT. The real bot uses the Microsoft 365 Agents SDK, which verifies
the token and posts replies back to the activity's serviceUrl.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from musk import handle_activity, make_activity, make_brain

BRAIN = make_brain()

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>@musk local chat</title>
<style>
 body{font:15px system-ui,sans-serif;margin:0;background:#f5f5f5;color:#242424}
 header{background:#464775;color:#fff;padding:12px 16px;font-weight:600}
 #log{max-width:760px;margin:0 auto;padding:16px}
 .m{background:#fff;border-radius:8px;padding:10px 14px;margin:8px 0;white-space:pre-wrap;box-shadow:0 1px 2px #0002}
 .me{background:#e8ebfa;margin-left:15%}.who{font-size:12px;color:#616161;margin-bottom:4px}
 form{position:sticky;bottom:0;max-width:760px;margin:0 auto;display:flex;gap:8px;padding:16px}
 input{flex:1;padding:10px;border:1px solid #ccc;border-radius:6px;font:inherit}
 button{padding:10px 16px;border:0;border-radius:6px;background:#5b5fc7;color:#fff;font:inherit}
</style>
<header>Weekly sync (meeting chat) &middot; @musk prototype</header>
<div id=log><div class=m><div class=who>tip</div>Try: @musk what's the takeaway from this meeting
@musk create ADO items for these topics
@musk add a wiki page to cover these ideas</div></div>
<form id=f><input id=t value="@musk what's the takeaway from this meeting" autocomplete=off><button>Send</button></form>
<script>
const log=document.getElementById('log');
function add(who,text,me){const d=document.createElement('div');d.className='m'+(me?' me':'');
 d.innerHTML='<div class=who></div><div></div>';d.children[0].textContent=who;d.children[1].textContent=text;log.appendChild(d);d.scrollIntoView();}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const t=document.getElementById('t');const text=t.value.trim();if(!text)return;
 add('You',text,true);t.value='';const r=await fetch('/api/simulate',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({text})});
 const j=await r.json();add('musk',j.reply?j.reply.text:'(not mentioned, staying quiet)');};
</script>"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/api/messages":
                reply = handle_activity(data, brain=BRAIN)
                self._json(200, reply or {})
            elif self.path == "/api/simulate":
                self._json(200, {"reply": handle_activity(make_activity(data.get("text", "")), brain=BRAIN)})
            else:
                self._json(404, {"error": "not found"})
        except Exception as e:  # keep the demo server alive
            self._json(500, {"error": str(e)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3978"))
    print(f"@musk listening on http://localhost:{port}  (brain: {type(BRAIN).__name__})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
