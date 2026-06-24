#!/usr/bin/env python3
"""Fast embed resolver - extracts video_id/server_id/quality"""
import argparse,gzip,json,os,re,urllib.error,urllib.parse,urllib.request,random
from dataclasses import dataclass,field,asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from typing import List

TIMEOUT=15
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

PROXIES=[
    ("31.59.20.176",6754),
    ("31.56.127.193",7684),
    ("45.38.107.97",6014),
    ("38.154.203.95",5863),
    ("198.105.121.200",6462),
    ("64.137.96.74",6641),
    ("198.23.243.226",6361),
    ("38.154.185.97",6370),
    ("142.111.67.146",5611),
    ("191.96.254.138",6185),
]
PROXY_USER="glsbcfvl"
PROXY_PASS="336gxb0or4n9"

# Known domains used by the embed flow
EMBED_ORIGIN="https://multiembed.mov"
STREAM_ORIGIN="https://streamingnow.mov"
STREAM_REFERER="https://streamingnow.mov/response.php"

TOKEN_RE=re.compile(r'[?&]play=([^&"\'<>]+)',re.I)
LOAD_RE=re.compile(r"""load_sources\(['"]([^'"]+)['"]\)""")
LI_RE=re.compile(r'<li\b([^>]*\bdata-id=[^>]*)>',re.I|re.S)
QUAL_RE=re.compile(r"""<span\b[^>]*class=['"][^'"]*\bquality\b[^'"]*['"][^>]*>(.*?)</span>""",re.I|re.S)
TAG_RE=re.compile(r'<(?:script|style)\b.*?</(?:script|style)>|<[^>]+>',re.I|re.S)

proxy_stats={f"{h}:{pt}":{"attempts":0,"success":0,"fail":0,"last_reason":""}for h,pt in PROXIES}

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
    proxy_used:str=""
    proxy_log:List[str]=field(default_factory=list)
    def j(self):
        return{"input_url":self.input_url,"ok":self.ok,"status":self.status,
               "sources":[asdict(s)for s in self.sources],"errors":self.errors,
               "proxy_used":self.proxy_used,"proxy_log":self.proxy_log}

def get_origin(url):
    p=urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"

def base_headers(url, referer=None, mode="navigate"):
    origin=get_origin(url)
    h={
        "User-Agent":UA,
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":"en-US,en;q=0.9",
        "Accept-Encoding":"gzip, deflate",
        "Connection":"keep-alive",
        "Upgrade-Insecure-Requests":"1",
        "Sec-Fetch-Dest":"document" if mode=="navigate" else "empty",
        "Sec-Fetch-Mode":mode,
        "Sec-Fetch-Site":"none" if not referer else "same-origin",
        "Sec-Fetch-User":"?1" if mode=="navigate" else None,
        "DNT":"1",
        "Cache-Control":"max-age=0",
        "Origin":origin,
    }
    if referer:h["Referer"]=referer
    # remove None values
    return{k:v for k,v in h.items()if v is not None}

def post_headers(url, referer=None):
    origin=get_origin(url)
    h={
        "User-Agent":UA,
        "Accept":"*/*",
        "Accept-Language":"en-US,en;q=0.9",
        "Accept-Encoding":"gzip, deflate",
        "Content-Type":"application/x-www-form-urlencoded",
        "X-Requested-With":"XMLHttpRequest",
        "Sec-Fetch-Mode":"cors",
        "Sec-Fetch-Dest":"empty",
        "Sec-Fetch-Site":"same-origin",
        "Origin":origin,
        "Connection":"keep-alive",
        "DNT":"1",
    }
    if referer:h["Referer"]=referer
    return h

def decode_body(raw,headers):
    ct=headers.get("Content-Encoding","")
    if "gzip" in ct:
        try:raw=gzip.decompress(raw)
        except Exception:pass
    return raw.decode("utf-8","replace")

def make_opener(host,port):
    proxy_url=f"http://{PROXY_USER}:{PROXY_PASS}@{host}:{port}"
    ph=urllib.request.ProxyHandler({"http":proxy_url,"https":proxy_url})
    opener=urllib.request.build_opener(ph,urllib.request.HTTPRedirectHandler())
    opener.addheaders=[]
    return opener

def do_request(req_factory, log, label):
    """Try all proxies in random order, retry on 403/429/503."""
    attempts=list(PROXIES);random.shuffle(attempts)
    last_err=None
    for host,port in attempts:
        key=f"{host}:{port}"
        proxy_stats[key]["attempts"]+=1
        opener=make_opener(host,port)
        req=req_factory()
        try:
            with opener.open(req,timeout=TIMEOUT)as resp:
                raw=resp.read()
                body=decode_body(raw,dict(resp.headers.items()))
                proxy_stats[key]["success"]+=1
                proxy_stats[key]["last_reason"]="ok"
                msg=f"[{label} OK] proxy={key} url={req.full_url}"
                log.append(msg);print(msg)
                return resp.status,resp.geturl(),dict(resp.headers.items()),body,key
        except urllib.error.HTTPError as e:
            reason=f"HTTP{e.code}"
            proxy_stats[key]["fail"]+=1
            proxy_stats[key]["last_reason"]=reason
            msg=f"[{label} FAIL] proxy={key} reason={reason} url={req.full_url}"
            log.append(msg);print(msg)
            body=e.read().decode("utf-8","replace")
            last_err=(e.code,req.full_url,dict(e.headers.items()),body,key)
            if e.code in(403,429,503):continue  # try next proxy
            return last_err
        except Exception as e:
            reason=f"{type(e).__name__}:{e}"
            proxy_stats[key]["fail"]+=1
            proxy_stats[key]["last_reason"]=reason
            msg=f"[{label} FAIL] proxy={key} reason={reason}"
            log.append(msg);print(msg)
            last_err=(0,req.full_url,{},reason,key)
            continue
    return last_err or (0,"",{},"all proxies failed","none")

def g(u, referer=None, log=None):
    if log is None:log=[]
    hdrs=base_headers(u,referer)
    def factory():return urllib.request.Request(u,headers=hdrs)
    return do_request(factory,log,"GET")

def p(u, d, referer=None, log=None):
    if log is None:log=[]
    hdrs=post_headers(u,referer)
    def factory():return urllib.request.Request(u,data=urllib.parse.urlencode(d).encode(),headers=hdrs,method="POST")
    return do_request(factory,log,"POST")

def tok(s):
    m=TOKEN_RE.search(s)
    if m:return urllib.parse.unquote(m.group(1))
    m=LOAD_RE.search(s)
    if m:return m.group(1)
    return None

def extract(html_body):
    s=[]
    ms=list(LI_RE.finditer(html_body))
    for i,m in enumerate(ms):
        a=m.group(1)
        vi=re.search(r"""data-id\s*=\s*['"](.*?)['"]""",a,re.I)
        si=re.search(r"""data-server\s*=\s*['"](.*?)['"]""",a,re.I)
        if not vi or not si:continue
        e=ms[i+1].start()if i+1<len(ms)else html_body.find("</ul>",m.end())
        if e<0:e=min(len(html_body),m.end()+200)
        f=html_body[m.end():e]
        qm=QUAL_RE.search(f)
        q=TAG_RE.sub(" ",qm.group(1)).strip()if qm else""
        s.append(Src(vi.group(1),si.group(1),q))
    return s

def resolve(u):
    r=R(u)
    log=r.proxy_log
    try:
        # Step 1: fetch embed page with multiembed.mov as origin
        s,fu,hd,bd,px=g(u, referer=EMBED_ORIGIN+"/", log=log)
        if s>=400:
            r.errors.append(f"HTTP{s} body={bd[:200]}")
            r.status="http_error"
            return r
        r.proxy_used=px

        # Step 2: find token
        pu=urllib.parse.urljoin(u,hd.get("Location")or hd.get("location")or fu)
        tk=tok(pu)or tok(bd)
        if not tk:
            _,_,_,pg,px2=g(pu, referer=EMBED_ORIGIN+"/", log=log)
            tk=tok(pg)
            if px2!="none":r.proxy_used=px2

        if not tk:
            r.errors.append("no token")
            r.status="no_token"
            return r

        # Step 3: POST to response.php with streamingnow.mov as origin+referer
        ru=urllib.parse.urljoin(pu,"/response.php")
        _,_,_,rh,px3=p(
            ru,
            {"token":tk},
            referer=STREAM_REFERER,
            log=log
        )
        if px3!="none":r.proxy_used=px3

        r.sources=extract(rh)
        r.ok=bool(r.sources)
        r.status="ok"if r.ok else"no_sources"
    except Exception as e:
        import traceback
        r.status="error"
        r.errors.append(f"{type(e).__name__}:{e}\n{traceback.format_exc()}")
    return r

def proxy_status_report():
    rows=[]
    for key,st in proxy_stats.items():
        if st["attempts"]==0:continue
        rows.append({"proxy":key,"success":st["success"],"fail":st["fail"],
                     "attempts":st["attempts"],"rate":f"{st['success']}/{st['attempts']}",
                     "last":st["last_reason"]})
    return rows

class H(BaseHTTPRequestHandler):
    server_version="FR/1"
    def do_GET(self):
        q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        try:
            if self.path.startswith("/health"):self.j({"ok":1});return
            if self.path.startswith("/proxy-status"):self.j({"proxies":proxy_status_report()});return
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
    ap=argparse.ArgumentParser()
    ap.add_argument("url",nargs="?",default="https://multiembed.mov/?video_id=280&tmdb=1")
    ap.add_argument("--serve",action="store_true")
    ap.add_argument("--port",type=int,default=int(os.environ.get("PORT","8787")))
    a=ap.parse_args()
    if a.serve:
        print(f"[server] listening on 127.0.0.1:{a.port}")
        ThreadingHTTPServer(("127.0.0.1",a.port),H).serve_forever()
        return
    r=resolve(a.url)
    out=r.j()
    out["proxy_stats"]=proxy_status_report()
    print(json.dumps(out,indent=2,ensure_ascii=False))
    return not r.ok

if __name__=="__main__":raise SystemExit(main())
