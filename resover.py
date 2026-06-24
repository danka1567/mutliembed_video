#!/usr/bin/env python3
"""Fast embed resolver - extracts video_id/server_id/quality"""
import argparse,html,json,os,re,sys,urllib.error,urllib.parse,urllib.request
from dataclasses import dataclass,field,asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from typing import Any,List,Optional,Tuple

TIMEOUT=8
UA="Mozilla/5.0"

TOKEN_RE=re.compile(r'[?&]play=([^&"\'<>]+)',re.I)
LOAD_RE=re.compile(r"""load_sources\(['"]([^'"]+)['"]\)""")
LI_RE=re.compile(r'<li\b([^>]*\bdata-id=[^>]*)>',re.I|re.S)
QUAL_RE=re.compile(r"""<span\b[^>]*class=['"][^'"]*\bquality\b[^'"]*['"][^>]*>(.*?)</span>""",re.I|re.S)
TAG_RE=re.compile(r'<(?:script|style)\b.*?</(?:script|style)>|<[^>]+>',re.I|re.S)

@dataclass
class Src:
    video_id:str
    server_id:str
    quality:str=""

@dataclass
class R:
    input_url:str
    ok:bool=False
    status:str=""
    sources:List[Src]=field(default_factory=list)
    errors:List[str]=field(default_factory=list)
    def j(self):
        return{"input_url":self.input_url,"ok":self.ok,"status":self.status,"sources":[asdict(s)for s in self.sources],"errors":self.errors}

class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a):return None

def g(u,r=None):
    h={"User-Agent":UA,"Accept":"text/html"}
    if r:h["Referer"]=r
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=h),timeout=TIMEOUT)as resp:
            return resp.status,resp.geturl(),dict(resp.headers.items()),resp.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code,u,dict(e.headers.items()),e.read().decode("utf-8","replace")

def p(u,d,r=None):
    h={"User-Agent":UA,"Content-Type":"application/x-www-form-urlencoded","X-Requested-With":"XMLHttpRequest","Origin":f"{urllib.parse.urlsplit(u).scheme}://{urllib.parse.urlsplit(u).netloc}"}
    if r:h["Referer"]=r
    req=urllib.request.Request(u,data=urllib.parse.urlencode(d).encode(),headers=h,method="POST")
    with urllib.request.urlopen(req,timeout=TIMEOUT)as resp:
        return resp.status,resp.geturl(),dict(resp.headers.items()),resp.read().decode("utf-8","replace")

def t(s):
    m=TOKEN_RE.search(s)
    if m:return urllib.parse.unquote(m.group(1))
    m=LOAD_RE.search(s)
    if m:return m.group(1)
    return None

def x(html):
    s=[]
    for i,m in enumerate(ms:=list(LI_RE.finditer(html))):
        a=m.group(1)
        vi=re.search(r"""data-id\s*=\s*['"](.*?)['"]""",a,re.I)
        si=re.search(r"""data-server\s*=\s*['"](.*?)['"]""",a,re.I)
        if not vi or not si:continue
        e=ms[i+1].start()if i+1<len(ms)else html.find("</ul>",m.end())
        if e<0:e=min(len(html),m.end()+200)
        f=html[m.end():e]
        qm=QUAL_RE.search(f)
        q=TAG_RE.sub(" ",qm.group(1)).strip()if qm else""
        s.append(Src(vi.group(1),si.group(1),q))
    return s

def resolve(u):
    r=R(u)
    try:
        s,fu,hd,bd=g(u)
        if s>=400:r.errors.append(f"HTTP{s}");r.status="http_error";return r
        pu=urllib.parse.urljoin(u,hd.get("Location")or hd.get("location")or fu)
        tk=t(pu)or t(bd)
        if not tk:
            _,_,_,pg=g(pu,u)
            tk=t(pg)
        if not tk:r.errors.append("no token");r.status="no_token";return r
        ru=urllib.parse.urljoin(pu,"/response.php")
        _,_,_,rh=p(ru,{"token":tk},pu)
        r.sources=x(rh)
        r.ok=bool(r.sources)
        r.status="ok"if r.ok else"no_sources"
    except Exception as e:r.status="error";r.errors.append(f"{type(e).__name__}:{e}")
    return r

class H(BaseHTTPRequestHandler):
    server_version="FR/1"
    def do_GET(self):
        q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        try:
            if self.path.startswith("/health"):self.j({"ok":1});return
            if self.path.startswith("/resolve"):
                u=(q.get("url")or[""])[0]
                if not u:self.j({"ok":0,"error":"missing url"},400);return
                self.j(resolve(u).j());return
            self.j({"ok":0},404)
        except Exception as e:self.j({"ok":0,"error":str(e)},500)
    def log_message(self,*a):pass
    def j(self,d,s=200):
        b=json.dumps(d,separators=(',',':')).encode()
        self.send_response(s)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b)))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(b)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("url",nargs="?",default="https://multiembed.mov/?video_id=280&tmdb=1")
    p.add_argument("--serve",action="store_true")
    p.add_argument("--port",type=int,default=int(os.environ.get("PORT","8787")))
    a=p.parse_args()
    if a.serve:
        ThreadingHTTPServer(("127.0.0.1",a.port),H).serve_forever()
        return
    r=resolve(a.url)
    print(json.dumps(r.j(),indent=2,ensure_ascii=False))
    return not r.ok

if __name__=="__main__":raise SystemExit(main())
