#!/usr/bin/env python3
"""websearch.py — Exa + Brave web search CLI for the /search skill, with an A/B log.

Engines:
  exa    POST https://api.exa.ai/search        x-api-key: $EXA_API_KEY   $0.007/call (<=10 res) +$0.001/res above 10
         POST https://api.exa.ai/contents      $0.001/page per content type
         POST https://api.exa.ai/context       $0.007/call (Exa Code)
  brave  GET  https://api.search.brave.com/res/v1/web/search   X-Subscription-Token: $BRAVE_API_KEY   $0.005/req (receipt-verified)
         GET  https://api.search.brave.com/res/v1/llm/context  $0.005/req (assumed, not receipt-verified)

Commands:
  exa "<q>" --tag T [...]        one Exa search
  brave "<q>" --tag T [...]      one Brave search (web | llm/context)
  both "<q>" --tag T [...]       Exa + Brave in parallel, shared pair_id, compact side-by-side output
  contents <url...> [...]        Exa /contents (full page / subpages / freshness)
  context "<q>" [--tokens ...]   Exa /context (code / API / library context)
  verdict <pair_id> exa|brave|tie --why W [--note ...]
  report [--since 14d] [--out md|json]

Log: $WEBSEARCH_LOG (default ~/.claude/telemetry/search-ab/events.jsonl) — one JSON object per line (kind: call | verdict),
     written with a single os.write in O_APPEND (<=4096 bytes). Schema: references/ab-log.md.
Keys: EXA_API_KEY (fallback ~/.config/exa/key), BRAVE_API_KEY — env only, never printed.
stdout = result only (safe to pipe); stderr = [cost] / [warn] / [error].
Exit: 0 ok · 1 usage/validation · 2 no key · 3 API error · 4 timeout · 5 unparseable response.
Python 3.9 stdlib only (Bash tool python3 = /usr/bin/python3 3.9.6).
"""
import argparse
import datetime as _dt
import gzip
import html
import json
import math
import os
import re
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict

VERSION = "1.0.0"
EXA_BASE = "https://api.exa.ai"
BRAVE_BASE = "https://api.search.brave.com/res/v1"
LOG_PATH = os.path.expanduser(os.environ.get("WEBSEARCH_LOG", "~/.claude/telemetry/search-ab/events.jsonl"))
SELF = "python3 %s" % os.path.abspath(__file__)

TAGS = ["research", "sources", "news", "code", "people", "company", "product", "other"]
EXA_TYPES = ["auto", "fast", "instant", "deep-lite", "deep", "deep-reasoning", "keyword", "neural"]
EXA_CATEGORIES = ["company", "people", "publication", "news", "personal site", "financial report"]
WHY = ["relevance", "freshness", "coverage", "lang", "noise"]
BRAVE_FRESHNESS = ["pd", "pw", "pm", "py"]

DAILY_CAP_USD = 2.0
DEFAULT_TIMEOUT = 20
MAX_N = 25
BOTH_MAX_N = 10
BRAVE_MAX_N = 20
BRAVE_WEB_COST = 0.005      # receipt #2482-5413: "Search (per request) $0.005 each"
BRAVE_CTX_COST = 0.005      # assumed (not on the receipt)
EXA_SEARCH_COST = {"deep-lite": 0.012, "deep": 0.012, "deep-reasoning": 0.015}
EXA_SEARCH_DEFAULT_COST = 0.007
EXA_EXTRA_RESULT_COST = 0.001
EXA_PAGE_COST = 0.001

EXIT_OK, EXIT_USAGE, EXIT_NOKEY, EXIT_API, EXIT_TIMEOUT, EXIT_PARSE = 0, 1, 2, 3, 4, 5

SNIP_CAP = 160
TITLE_CAP = 70
PATH_CAP = 60


# ---------------------------------------------------------------- helpers
def err(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def die(msg, code=EXIT_USAGE):
    err("[error] " + msg)
    sys.exit(code)


class Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors -> exit 1, not argparse's 2
        self.print_usage(sys.stderr)
        die(message, EXIT_USAGE)


def now_iso():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def lang_of(q):
    letters = [c for c in q if c.isalpha()]
    if not letters:
        return "en"
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    share = cyr / len(letters)
    if share >= 0.3:
        return "ru"
    if share <= 0.1:
        return "en"
    return "mixed"


def domain_of(url):
    try:
        net = urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return ""
    if net.startswith("www."):
        net = net[4:]
    return net.split("@")[-1].split(":")[0]


def one_line(s):
    return re.sub(r"\s+", " ", s or "").strip()


def cut(s, n):
    s = one_line(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def url_path(url, cap=PATH_CAP):
    u = re.sub(r"^https?://", "", url or "")
    if u.startswith("www."):
        u = u[4:]
    u = u.rstrip("/")
    return cut(u, cap)


def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_patch(s):
    if not s:
        return {}
    try:
        d = json.loads(s)
    except ValueError as e:
        die("--json-patch is not valid JSON: %s" % e)
    if not isinstance(d, dict):
        die("--json-patch must be a JSON object")
    return d


def valid_date(s, flag):
    if s is None:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?$", s):
        die("%s must be YYYY-MM-DD (ISO 8601), got %r" % (flag, s))
    return s


def csv_list(s):
    if not s:
        return None
    items = [x.strip() for x in s.split(",") if x.strip()]
    return items or None


def fmt_usd(x):
    return "$%.4f" % x if x < 0.01 else "$%.3f" % x


# ---------------------------------------------------------------- keys
def exa_key():
    k = os.environ.get("EXA_API_KEY", "").strip()
    if k:
        return k
    p = os.path.expanduser("~/.config/exa/key")
    try:
        with open(p) as f:
            k = f.read().strip()
            if k:
                return k
    except OSError:
        pass
    return None


def brave_key():
    return os.environ.get("BRAVE_API_KEY", "").strip() or None


# ---------------------------------------------------------------- log
def log_event(rec, enabled=True):
    if not enabled:
        return
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    if len(line.encode("utf-8")) > 4096:
        rec = dict(rec)
        rec["top_urls"] = [u[:120] for u in (rec.get("top_urls") or [])][:3]
        rec["query"] = (rec.get("query") or "")[:150]
        rec["err"] = (rec.get("err") or None) and rec["err"][:120]
        rec["note"] = (rec.get("note") or None) and rec["note"][:150]
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    data = (line + "\n").encode("utf-8")
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        fd = os.open(LOG_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError as e:
        err("[warn] log write failed: %s" % e)


def read_log():
    recs, bad = [], 0
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if isinstance(d, dict) and d.get("kind") in ("call", "verdict"):
                        recs.append(d)
                    else:
                        bad += 1
                except ValueError:
                    bad += 1
    except OSError:
        pass
    return recs, bad


def spent_today():
    today = _dt.date.today().isoformat()
    recs, _ = read_log()
    return sum(float(r.get("cost_usd") or 0) for r in recs
               if r.get("kind") == "call" and (r.get("ts") or "")[:10] == today)


def check_cap(planned, force):
    spent = spent_today()
    if not force and spent + planned >= DAILY_CAP_USD:
        die("daily soft cap %s reached (spent today %s, planned %s) — rerun with --force to override"
            % (fmt_usd(DAILY_CAP_USD), fmt_usd(spent), fmt_usd(planned)), EXIT_USAGE)
    if spent + planned >= DAILY_CAP_USD * 0.75:
        err("[warn] spent today %s of %s soft cap" % (fmt_usd(spent + planned), fmt_usd(DAILY_CAP_USD)))


# ---------------------------------------------------------------- HTTP
class TimeoutErr(Exception):
    pass


def http_json(method, url, headers, body=None, timeout=DEFAULT_TIMEOUT):
    """Returns (status, parsed_json_or_text, latency_ms). Raises TimeoutErr on timeout."""
    data = None
    hdrs = dict(headers)
    hdrs.setdefault("Accept", "application/json")
    hdrs.setdefault("Accept-Encoding", "gzip")
    hdrs.setdefault("User-Agent", "websearch.py/%s (+claude-code /search)" % VERSION)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
            enc = resp.headers.get("Content-Encoding", "")
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        enc = e.headers.get("Content-Encoding", "") if e.headers else ""
    except (socket.timeout, TimeoutError):
        raise TimeoutErr()
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)) or "timed out" in str(e.reason):
            raise TimeoutErr()
        raise
    latency = int((time.monotonic() - t0) * 1000)
    if "gzip" in (enc or "") or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text) if text.strip() else {}
    except ValueError:
        parsed = text
    return status, parsed, latency


def cost_total(parsed):
    """costDollars.total from an Exa response; /context returns costDollars as a JSON *string*."""
    if not isinstance(parsed, dict):
        return None
    cd = parsed.get("costDollars")
    if isinstance(cd, str):
        try:
            cd = json.loads(cd)
        except ValueError:
            return None
    if isinstance(cd, dict) and isinstance(cd.get("total"), (int, float)):
        return float(cd["total"])
    return None


def error_text(status, parsed):
    """Compact error string from an API error body."""
    msg = ""
    if isinstance(parsed, dict):
        e = parsed.get("error")
        if isinstance(e, dict):
            code = e.get("code") or e.get("tag") or ""
            detail = e.get("detail") or e.get("message") or ""
            msg = ("%s: %s" % (code, detail)).strip(": ")
        elif isinstance(e, str):
            msg = e
        else:
            msg = parsed.get("message") or parsed.get("detail") or json.dumps(parsed, ensure_ascii=False)
    else:
        msg = str(parsed)
    return cut("HTTP %d %s" % (status, msg), 200)


# ---------------------------------------------------------------- engine results
def mk_result(engine, mode, cmd, n_req):
    return {"engine": engine, "mode": mode, "cmd": cmd, "n_req": n_req, "ok": False, "http": 0,
            "latency_ms": 0, "cost_usd": 0.0, "cost_src": "fixed", "results": [], "err": None,
            "raw": None, "timeout": False}


def norm_exa_result(r):
    snippet = ""
    if r.get("highlights"):
        snippet = r["highlights"][0]
    elif r.get("summary"):
        snippet = r["summary"]
    elif r.get("text"):
        snippet = r["text"]
    date = (r.get("publishedDate") or "")[:10]
    return {"title": r.get("title") or "", "url": r.get("url") or r.get("id") or "", "date": date,
            "snippet": snippet or "", "domain": domain_of(r.get("url") or r.get("id") or "")}


def norm_brave_web(r):
    snippet = strip_html(r.get("description") or "")
    if not snippet and r.get("extra_snippets"):
        snippet = r["extra_snippets"][0]
    date = r.get("page_age") or r.get("age") or ""
    return {"title": strip_html(r.get("title") or ""), "url": r.get("url") or "", "date": date[:10],
            "snippet": snippet, "domain": domain_of(r.get("url") or "")}


def norm_brave_ctx(g, sources):
    url = g.get("url") or ""
    src = (sources or {}).get(url) or {}
    snippet = (g.get("snippets") or [""])[0]
    return {"title": g.get("title") or src.get("title") or "", "url": url, "date": (src.get("age") or "")[:10],
            "snippet": snippet, "domain": domain_of(url)}


# ---------------------------------------------------------------- Exa
def exa_search_body(a):
    body = {"query": a.query, "type": a.type, "numResults": a.n}
    if a.category:
        body["category"] = a.category
    inc, exc = csv_list(a.include_domains), csv_list(a.exclude_domains)
    if inc:
        body["includeDomains"] = inc
    if exc:
        body["excludeDomains"] = exc
    if a.start:
        body["startPublishedDate"] = a.start
    if a.end:
        body["endPublishedDate"] = a.end
    if a.country:
        body["userLocation"] = a.country.upper()
    contents = {}
    mode = a.contents
    if mode == "highlights":
        contents["highlights"] = True
    elif mode == "text":
        contents["text"] = True if a.full or not a.max_chars else {"maxCharacters": a.max_chars}
    elif mode == "summary":
        contents["summary"] = {"query": a.summary_query} if a.summary_query else True
    if a.max_age_hours is not None:
        contents["maxAgeHours"] = a.max_age_hours
        contents["livecrawlTimeout"] = 12000
    if contents:
        body["contents"] = contents
    if getattr(a, "json_patch", None):
        body = deep_merge(body, parse_patch(a.json_patch))
    return body


def exa_estimate(body):
    t = body.get("type", "auto")
    n = int(body.get("numResults", 10) or 10)
    cost = EXA_SEARCH_COST.get(t, EXA_SEARCH_DEFAULT_COST) + max(0, n - 10) * EXA_EXTRA_RESULT_COST
    if isinstance(body.get("contents"), dict) and body["contents"].get("summary"):
        cost += n * EXA_PAGE_COST
    return cost


def run_exa_search(body, key, timeout):
    res = mk_result("exa", body.get("type", "auto"), "search", int(body.get("numResults", 10) or 10))
    try:
        status, parsed, lat = http_json("POST", EXA_BASE + "/search", {"x-api-key": key}, body, timeout)
    except TimeoutErr:
        res.update(err="timeout after %ds" % timeout, timeout=True, latency_ms=timeout * 1000)
        return res
    except Exception as e:  # network
        res.update(err=cut("network: %s" % e, 200))
        return res
    res.update(http=status, latency_ms=lat, raw=parsed)
    if status != 200:
        res["err"] = error_text(status, parsed)
        return res
    if not isinstance(parsed, dict) or "results" not in parsed:
        res["err"] = cut("unparseable response: %s" % str(parsed)[:200], 200)
        return res
    res["results"] = [norm_exa_result(r) for r in parsed.get("results") or []]
    ct = cost_total(parsed)
    if ct is not None:
        res["cost_usd"], res["cost_src"] = ct, "api"
    else:
        res["cost_usd"], res["cost_src"] = exa_estimate(body), "fixed"
    res["ok"] = True
    return res


# ---------------------------------------------------------------- Brave
def brave_params(a, mode):
    p = {"q": a.query, "count": a.n}
    if mode == "web":
        p["extra_snippets"] = "true"
    else:
        p["maximum_number_of_tokens"] = getattr(a, "tokens_brave", None) or 8192
        if getattr(a, "threshold", None):
            p["context_threshold_mode"] = a.threshold
    if a.country:
        p["country"] = a.country.upper()
    if getattr(a, "lang", None):
        p["search_lang"] = a.lang
    if getattr(a, "freshness", None):
        p["freshness"] = a.freshness
    if getattr(a, "goggles", None):
        p["goggles"] = a.goggles
    if getattr(a, "json_patch", None):
        p = deep_merge(p, parse_patch(a.json_patch))
    return p


def brave_url(mode, params):
    path = "/web/search" if mode == "web" else "/llm/context"
    items = []
    for k, v in params.items():
        if isinstance(v, list):
            for x in v:
                items.append((k, str(x)))
        elif isinstance(v, bool):
            items.append((k, "true" if v else "false"))
        else:
            items.append((k, str(v)))
    return BRAVE_BASE + path + "?" + urllib.parse.urlencode(items)


def run_brave(mode, params, key, timeout):
    res = mk_result("brave", mode, mode, int(params.get("count", 10) or 10))
    res["cost_src"] = "fixed" if mode == "web" else "assumed"
    try:
        status, parsed, lat = http_json("GET", brave_url(mode, params), {"X-Subscription-Token": key}, None, timeout)
    except TimeoutErr:
        res.update(err="timeout after %ds" % timeout, timeout=True, latency_ms=timeout * 1000)
        return res
    except Exception as e:
        res.update(err=cut("network: %s" % e, 200))
        return res
    res.update(http=status, latency_ms=lat, raw=parsed)
    if status != 200:
        res["err"] = error_text(status, parsed)
        return res
    if not isinstance(parsed, dict):
        res["err"] = cut("unparseable response: %s" % str(parsed)[:200], 200)
        return res
    if mode == "web":
        web = parsed.get("web") or {}
        res["results"] = [norm_brave_web(r) for r in web.get("results") or []]
        res["cost_usd"] = BRAVE_WEB_COST
    else:
        gr = parsed.get("grounding") or {}
        res["results"] = [norm_brave_ctx(g, parsed.get("sources")) for g in gr.get("generic") or []]
        res["cost_usd"] = BRAVE_CTX_COST
    res["ok"] = True
    return res


# ---------------------------------------------------------------- rendering
def engine_header(r, label=None):
    name = (label or r["engine"]).upper()
    if r["ok"]:
        return "── %s %s · %d ms · %s · %d res" % (name, r["mode"], r["latency_ms"], fmt_usd(r["cost_usd"]), len(r["results"]))
    return "── %s НЕДОСТУПЕН %s · %d ms" % (name, r["err"] or "?", r["latency_ms"])


def render_results(results, full=False, snippets=True):
    lines = []
    for i, x in enumerate(results, 1):
        path = url_path(x["url"], 10 ** 6 if full else PATH_CAP)
        title = x["title"] if full else cut(x["title"], TITLE_CAP)
        head = "%2d %s · %s" % (i, path, title)
        if x.get("date"):
            head += " · " + x["date"]
        lines.append(head)
        if snippets and x.get("snippet"):
            lines.append("   ↳ " + (one_line(x["snippet"]) if full else cut(x["snippet"], SNIP_CAP)))
    return lines


def top_domains(results, k=5):
    seen = []
    for x in results:
        d = x.get("domain")
        if d and d not in seen:
            seen.append(d)
        if len(seen) >= k:
            break
    return seen


def overlap_lines(exa, brave):
    a, b = top_domains(exa["results"]), top_domains(brave["results"])
    shared = [d for d in a if d in b]
    only_a = [d for d in a if d not in b][:4]
    only_b = [d for d in b if d not in a][:4]
    line = "── OVERLAP top-5 доменов %d/5" % len(shared)
    if only_a:
        line += " · только exa: " + ", ".join(only_a)
    if only_b:
        line += " · только brave: " + ", ".join(only_b)
    return [line]


def print_single(r, a, extra_meta=None):
    if a.out == "json":
        meta = {"engine": r["engine"], "mode": r["mode"], "http": r["http"], "latency_ms": r["latency_ms"],
                "cost_usd": r["cost_usd"], "cost_src": r["cost_src"], "n_res": len(r["results"]), "err": r["err"]}
        if extra_meta:
            meta.update(extra_meta)
        print(json.dumps({"_meta": meta, "response": r["raw"]}, ensure_ascii=False, indent=1))
        return
    if a.out == "urls":
        for x in r["results"]:
            print(x["url"])
        return
    print(engine_header(r))
    for line in render_results(r["results"], full=a.full):
        print(line)


def call_record(r, host_cmd, query, tag, pair_id=None, degraded=False):
    return {"kind": "call", "ts": now_iso(), "pair_id": pair_id, "host_cmd": host_cmd, "engine": r["engine"],
            "cmd": r["cmd"], "mode": r["mode"], "query": cut(query, 300), "lang": lang_of(query), "tag": tag,
            "n_req": r["n_req"], "n_res": len(r["results"]), "latency_ms": r["latency_ms"],
            "cost_usd": round(float(r["cost_usd"]), 6), "cost_src": r["cost_src"], "http": r["http"],
            "top_urls": [x["url"][:200] for x in r["results"][:5]], "top_domains": top_domains(r["results"]),
            "err": r["err"], "degraded": degraded}


def cost_line(r, query):
    err("[cost] %s %s %s (%s) %d ms | %s" % (r["engine"], r["mode"], fmt_usd(r["cost_usd"]), r["cost_src"],
                                            r["latency_ms"], cut(query, 60)))


def exit_for(r):
    if r["ok"]:
        return EXIT_OK
    if r["timeout"]:
        return EXIT_TIMEOUT
    if r["http"] == 200:
        return EXIT_PARSE
    return EXIT_API


def dry_run_print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- commands
def validate_exa_args(a, max_n=MAX_N):
    if a.n < 1 or a.n > max_n:
        die("-n must be 1..%d (Exa best practice: never above 25 — run more angles instead)" % max_n)
    if a.category in ("company", "people") and (a.start or a.end or csv_list(a.exclude_domains)):
        die("category %r does not support --start/--end/--exclude-domains (API returns 400)" % a.category)
    if a.category == "people" and csv_list(a.include_domains):
        if any("linkedin.com" not in d for d in csv_list(a.include_domains)):
            die("category people accepts only LinkedIn domains in --include-domains")
    valid_date(a.start, "--start")
    valid_date(a.end, "--end")
    if a.type in ("keyword", "neural"):
        err("[warn] type %r is legacy (not in the documented enum) — on HTTP 400 retry with --type auto" % a.type)


def cmd_exa(a):
    validate_exa_args(a)
    body = exa_search_body(a)
    if a.dry_run:
        dry_run_print({"engine": "exa", "method": "POST", "url": EXA_BASE + "/search",
                       "headers": {"x-api-key": "${EXA_API_KEY}"}, "body": body})
        return EXIT_OK
    key = exa_key()
    if not key:
        die("EXA_API_KEY not set — add `export EXA_API_KEY=…` to ~/.zshenv (or ~/.config/exa/key)", EXIT_NOKEY)
    check_cap(exa_estimate(body), a.force)
    r = run_exa_search(body, key, a.timeout)
    cost_line(r, a.query)
    log_event(call_record(r, "exa", a.query, a.tag), not a.no_log)
    if not r["ok"]:
        err("[error] exa: %s" % r["err"])
        if r["http"] == 400 and body.get("type") in ("keyword", "neural"):
            err("[hint] legacy type rejected — retry with --type auto")
        return exit_for(r)
    print_single(r, a)
    return EXIT_OK


def cmd_brave(a):
    if a.n < 1 or a.n > BRAVE_MAX_N:
        die("-n must be 1..%d for Brave" % BRAVE_MAX_N)
    if a.freshness and a.freshness not in BRAVE_FRESHNESS and not re.match(r"^\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}$", a.freshness):
        die("--freshness must be pd|pw|pm|py or YYYY-MM-DDtoYYYY-MM-DD")
    params = brave_params(a, a.mode)
    if a.dry_run:
        dry_run_print({"engine": "brave", "method": "GET", "url": brave_url(a.mode, params),
                       "headers": {"X-Subscription-Token": "${BRAVE_API_KEY}"}, "params": params})
        return EXIT_OK
    key = brave_key()
    if not key:
        die("BRAVE_API_KEY not set — add `export BRAVE_API_KEY=…` to ~/.zshenv", EXIT_NOKEY)
    check_cap(BRAVE_WEB_COST if a.mode == "web" else BRAVE_CTX_COST, a.force)
    r = run_brave(a.mode, params, key, a.timeout)
    cost_line(r, a.query)
    log_event(call_record(r, "brave", a.query, a.tag), not a.no_log)
    if not r["ok"]:
        err("[error] brave: %s" % r["err"])
        return exit_for(r)
    print_single(r, a)
    return EXIT_OK


def cmd_both(a):
    if a.n > BOTH_MAX_N:
        err("[warn] both caps -n at %d (was %d)" % (BOTH_MAX_N, a.n))
        a.n = BOTH_MAX_N
    if a.n < 1:
        die("-n must be >= 1")
    exa_query = a.query_exa or a.query
    ea = argparse.Namespace(query=exa_query, type=a.type, n=a.n, category=None, include_domains=None,
                            exclude_domains=None, start=None, end=None, country=a.country, contents="highlights",
                            summary_query=None, max_chars=None, full=False, max_age_hours=None, json_patch=None)
    validate_exa_args(ea, BOTH_MAX_N)
    body = exa_search_body(ea)
    ba = argparse.Namespace(query=a.query, n=a.n, country=a.country, lang=a.lang, freshness=None, goggles=None,
                            json_patch=None, tokens_brave=None, threshold=None)
    params = brave_params(ba, a.mode)
    if a.dry_run:
        dry_run_print({"pair_id": "dry-run",
                       "exa": {"method": "POST", "url": EXA_BASE + "/search", "headers": {"x-api-key": "${EXA_API_KEY}"}, "body": body},
                       "brave": {"method": "GET", "url": brave_url(a.mode, params), "headers": {"X-Subscription-Token": "${BRAVE_API_KEY}"}, "params": params}})
        return EXIT_OK
    ek, bk = exa_key(), brave_key()
    if not ek and not bk:
        die("neither EXA_API_KEY nor BRAVE_API_KEY is set (~/.zshenv)", EXIT_NOKEY)
    planned = exa_estimate(body) + (BRAVE_WEB_COST if a.mode == "web" else BRAVE_CTX_COST)
    check_cap(planned, a.force)
    pair_id = uuid.uuid4().hex[:8]
    box = {}

    def run_e():
        box["exa"] = run_exa_search(body, ek, a.timeout) if ek else _nokey("exa", body.get("type", "auto"), "search", a.n, "EXA_API_KEY not set")

    def run_b():
        box["brave"] = run_brave(a.mode, params, bk, a.timeout) if bk else _nokey("brave", a.mode, a.mode, a.n, "BRAVE_API_KEY not set")

    te, tb = threading.Thread(target=run_e), threading.Thread(target=run_b)
    te.start()
    tb.start()
    te.join(a.timeout + 5)
    tb.join(a.timeout + 5)
    re_, rb = box.get("exa") or _nokey("exa", a.type, "search", a.n, "thread died"), box.get("brave") or _nokey("brave", a.mode, a.mode, a.n, "thread died")
    degraded = not (re_["ok"] and rb["ok"])
    cost_line(re_, exa_query)
    cost_line(rb, a.query)
    log_event(call_record(re_, "both", exa_query, a.tag, pair_id, degraded), not a.no_log)
    log_event(call_record(rb, "both", a.query, a.tag, pair_id, degraded), not a.no_log)

    if a.out == "json":
        print(json.dumps({"pair_id": pair_id, "tag": a.tag, "lang": lang_of(a.query), "degraded": degraded,
                          "exa": {k: v for k, v in re_.items() if k != "raw"} if a.no_raw else re_,
                          "brave": {k: v for k, v in rb.items() if k != "raw"} if a.no_raw else rb}, ensure_ascii=False, indent=1))
    elif a.out == "urls":
        for x in re_["results"]:
            print("exa\t" + x["url"])
        for x in rb["results"]:
            print("brave\t" + x["url"])
    else:
        head = "pair=%s tag=%s lang=%s n=%d  q=%s" % (pair_id, a.tag, lang_of(a.query), a.n, json.dumps(cut(a.query, 100), ensure_ascii=False))
        if a.query_exa:
            head += "  q_exa=%s" % json.dumps(cut(exa_query, 100), ensure_ascii=False)
        print(head)
        print(engine_header(re_))
        for line in render_results(re_["results"], full=a.full):
            print(line)
        print(engine_header(rb))
        for line in render_results(rb["results"], full=a.full):
            print(line)
        if degraded:
            dead = [r["engine"] for r in (re_, rb) if not r["ok"]]
            print("── PAIR DEGRADED (%s) — вердикт не требуется" % ", ".join("%s: %s" % (r["engine"], cut(r["err"] or "?", 80)) for r in (re_, rb) if not r["ok"]))
            err("[warn] pair %s degraded: %s down" % (pair_id, ", ".join(dead)))
        else:
            for line in overlap_lines(re_, rb):
                print(line)
            print("verdict: %s verdict %s exa|brave|tie --why relevance|freshness|coverage|lang|noise [--note \"…\"]" % (SELF, pair_id))
    if re_["ok"] or rb["ok"]:
        return EXIT_OK
    if re_["timeout"] and rb["timeout"]:
        return EXIT_TIMEOUT
    return EXIT_API


def _nokey(engine, mode, cmd, n, msg):
    r = mk_result(engine, mode, cmd, n)
    r["err"] = msg
    return r


def cmd_contents(a):
    urls = a.urls
    if not urls:
        die("at least one URL is required")
    for u in urls:
        if not re.match(r"^https?://", u):
            die("not a URL: %r" % u)
    mode = a.mode_contents or "text"
    body = {"urls": urls}
    if mode == "text":
        body["text"] = True if (a.full or not a.max_chars) else {"maxCharacters": a.max_chars}
    elif mode == "highlights":
        body["highlights"] = True
    else:
        body["summary"] = {"query": a.summary_query} if a.summary_query else True
    if a.subpages:
        body["subpages"] = a.subpages
        if a.subpage_target:
            body["subpageTarget"] = csv_list(a.subpage_target)
    if a.max_age_hours is not None:
        body["maxAgeHours"] = a.max_age_hours
        body["livecrawlTimeout"] = a.livecrawl_timeout or 12000
    elif a.livecrawl_timeout:
        body["livecrawlTimeout"] = a.livecrawl_timeout
    if a.json_patch:
        body = deep_merge(body, parse_patch(a.json_patch))
    if a.dry_run:
        dry_run_print({"engine": "exa", "method": "POST", "url": EXA_BASE + "/contents",
                       "headers": {"x-api-key": "${EXA_API_KEY}"}, "body": body})
        return EXIT_OK
    key = exa_key()
    if not key:
        die("EXA_API_KEY not set — add `export EXA_API_KEY=…` to ~/.zshenv", EXIT_NOKEY)
    est = EXA_PAGE_COST * len(urls) * (1 + (a.subpages or 0))
    check_cap(est, a.force)
    r = mk_result("exa", mode, "contents", len(urls))
    try:
        status, parsed, lat = http_json("POST", EXA_BASE + "/contents", {"x-api-key": key}, body, max(a.timeout, 30))
    except TimeoutErr:
        r.update(err="timeout", timeout=True, latency_ms=a.timeout * 1000)
        status, parsed, lat = 0, None, 0
    except Exception as e:
        r.update(err=cut("network: %s" % e, 200))
        status, parsed, lat = 0, None, 0
    label = urls[0] + (" (+%d)" % (len(urls) - 1) if len(urls) > 1 else "")
    if status:
        r.update(http=status, latency_ms=lat, raw=parsed)
    if status == 200 and isinstance(parsed, dict) and "results" in parsed:
        r["results"] = [norm_exa_result(x) for x in parsed.get("results") or []]
        ct = cost_total(parsed)
        if ct is not None:
            r["cost_usd"], r["cost_src"] = ct, "api"
        else:
            r["cost_usd"], r["cost_src"] = EXA_PAGE_COST * max(1, len(parsed.get("results") or [])), "fixed"
        r["ok"] = True
    elif status and status != 200:
        r["err"] = error_text(status, parsed)
    elif status == 200:
        r["err"] = cut("unparseable response: %s" % str(parsed)[:200], 200)
    cost_line(r, label)
    log_event(call_record(r, "contents", label, a.tag), not a.no_log)
    if not r["ok"]:
        err("[error] exa contents: %s" % r["err"])
        return exit_for(r)
    statuses = parsed.get("statuses") or []
    failed = [s for s in statuses if s.get("status") != "success"]
    for s in failed:
        e = s.get("error") or {}
        err("[warn] %s → %s (%s)" % (s.get("id"), e.get("tag") or "error", e.get("httpStatusCode") or "?"))
    if a.out == "json":
        print(json.dumps({"_meta": {"latency_ms": lat, "cost_usd": r["cost_usd"], "cost_src": r["cost_src"]}, "response": parsed}, ensure_ascii=False, indent=1))
        return EXIT_OK
    if a.out == "urls":
        for x in parsed.get("results") or []:
            print(x.get("url") or x.get("id"))
            for sp in x.get("subpages") or []:
                print(sp.get("url") or sp.get("id"))
        return EXIT_OK
    print("── EXA contents %s · %d ms · %s · %d/%d ok" % (mode, lat, fmt_usd(r["cost_usd"]), len(parsed.get("results") or []), len(urls)))
    for x in parsed.get("results") or []:
        _print_content(x, mode, a.full, indent="")
        for sp in x.get("subpages") or []:
            print("   ↳ subpage")
            _print_content(sp, mode, a.full, indent="   ")
    return EXIT_OK


def _print_content(x, mode, full, indent=""):
    title = x.get("title") or ""
    date = (x.get("publishedDate") or "")[:10]
    print("%s# %s · %s%s" % (indent, x.get("url") or x.get("id"), cut(title, 100), (" · " + date) if date else ""))
    if mode == "text":
        body = x.get("text") or ""
    elif mode == "highlights":
        body = "\n".join("- " + one_line(h) for h in x.get("highlights") or [])
    else:
        body = x.get("summary") or ""
    if not full and mode == "text" and len(body) > 12000:
        body = body[:12000] + "\n…[truncated at 12000 chars — use --full or --max-chars]"
    for line in body.splitlines():
        print(indent + line)
    print()


def cmd_context(a):
    tokens = a.tokens
    if tokens != "dynamic":
        try:
            tokens = int(tokens)
        except ValueError:
            die("--tokens must be 'dynamic' or an integer 50..100000")
        if tokens < 50 or tokens > 100000:
            die("--tokens must be 50..100000")
    if len(a.query) > 2000:
        die("query must be <= 2000 chars for /context")
    body = {"query": a.query, "tokensNum": tokens}
    if a.json_patch:
        body = deep_merge(body, parse_patch(a.json_patch))
    if a.dry_run:
        dry_run_print({"engine": "exa", "method": "POST", "url": EXA_BASE + "/context",
                       "headers": {"x-api-key": "${EXA_API_KEY}"}, "body": body})
        return EXIT_OK
    key = exa_key()
    if not key:
        die("EXA_API_KEY not set — add `export EXA_API_KEY=…` to ~/.zshenv", EXIT_NOKEY)
    check_cap(EXA_SEARCH_DEFAULT_COST, a.force)
    r = mk_result("exa", str(tokens), "context", 1)
    try:
        status, parsed, lat = http_json("POST", EXA_BASE + "/context", {"x-api-key": key}, body, a.timeout)
    except TimeoutErr:
        r.update(err="timeout", timeout=True, latency_ms=a.timeout * 1000)
        status, parsed, lat = 0, None, 0
    except Exception as e:
        r.update(err=cut("network: %s" % e, 200))
        status, parsed, lat = 0, None, 0
    if status:
        r.update(http=status, latency_ms=lat, raw=parsed)
    if status == 200 and isinstance(parsed, dict) and "response" in parsed:
        r["ok"] = True
        r["results"] = []
        ct = cost_total(parsed)
        if ct is not None:
            r["cost_usd"], r["cost_src"] = ct, "api"
        else:
            r["cost_usd"], r["cost_src"] = EXA_SEARCH_DEFAULT_COST, "fixed"
        r["n_res"] = parsed.get("resultsCount") or 0
    elif status and status != 200:
        r["err"] = error_text(status, parsed)
    elif status == 200:
        r["err"] = cut("unparseable response: %s" % str(parsed)[:200], 200)
    cost_line(r, a.query)
    rec = call_record(r, "context", a.query, a.tag)
    if r["ok"]:
        rec["n_res"] = int(parsed.get("resultsCount") or 0)
    log_event(rec, not a.no_log)
    if not r["ok"]:
        err("[error] exa context: %s" % r["err"])
        return exit_for(r)
    if a.out == "json":
        print(json.dumps({"_meta": {"latency_ms": lat, "cost_usd": r["cost_usd"], "cost_src": r["cost_src"]}, "response": parsed}, ensure_ascii=False, indent=1))
        return EXIT_OK
    print("── EXA context · %d ms · %s · %s results · %s tokens" % (lat, fmt_usd(r["cost_usd"]), parsed.get("resultsCount"), parsed.get("outputTokens")))
    print(parsed.get("response") or "")
    return EXIT_OK


def cmd_verdict(a):
    if not re.match(r"^[0-9a-f]{8}$", a.pair_id):
        die("pair_id must be 8 hex chars (from the `both` output)")
    recs, _ = read_log()
    calls = [r for r in recs if r.get("kind") == "call" and r.get("pair_id") == a.pair_id]
    if not calls and not a.force:
        die("pair %s not found in %s (use --force to record anyway)" % (a.pair_id, LOG_PATH))
    if any(c.get("degraded") for c in calls):
        err("[warn] pair %s is degraded (one engine failed) — verdict recorded but excluded from comparable stats" % a.pair_id)
    prev = [r for r in recs if r.get("kind") == "verdict" and r.get("pair_id") == a.pair_id]
    if prev:
        err("[warn] pair %s already has %d verdict(s); the latest one wins in report" % (a.pair_id, len(prev)))
    rec = {"kind": "verdict", "ts": now_iso(), "pair_id": a.pair_id, "winner": a.winner, "why": a.why,
           "note": cut(a.note, 300) if a.note else None}
    if a.dry_run:
        dry_run_print(rec)
        return EXIT_OK
    log_event(rec, not a.no_log)
    tag = calls[0].get("tag") if calls else "?"
    print("verdict recorded: pair=%s winner=%s why=%s tag=%s" % (a.pair_id, a.winner, a.why, tag))
    return EXIT_OK


# ---------------------------------------------------------------- report
def wilson_lb(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - adj) / denom


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def parse_since(s):
    m = re.match(r"^(\d+)d$", s or "")
    if m:
        return _dt.datetime.now().astimezone() - _dt.timedelta(days=int(m.group(1)))
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        die("--since must be Nd (e.g. 14d) or YYYY-MM-DD")
    if d.tzinfo is None:
        d = d.astimezone()
    return d


def ts_of(rec):
    try:
        d = _dt.datetime.fromisoformat(rec.get("ts") or "")
        return d if d.tzinfo else d.astimezone()
    except ValueError:
        return None


def build_report(since):
    recs, bad = read_log()
    calls = [r for r in recs if r.get("kind") == "call" and (ts_of(r) or since) >= since]
    verdicts = [r for r in recs if r.get("kind") == "verdict" and (ts_of(r) or since) >= since]
    by_pair = defaultdict(list)
    for c in calls:
        if c.get("pair_id"):
            by_pair[c["pair_id"]].append(c)
    pairs = {p: cs for p, cs in by_pair.items() if {c["engine"] for c in cs} >= {"exa", "brave"}}
    comparable = {p: cs for p, cs in pairs.items()
                  if all(not c.get("err") and c.get("http") == 200 and not c.get("degraded") for c in cs)}
    latest_verdict = {}
    for v in verdicts:
        latest_verdict[v["pair_id"]] = v  # file order = time order
    cmp_verdicts = {p: v for p, v in latest_verdict.items() if p in comparable}

    # engines table by engine/mode
    eng = {}
    for c in calls:
        k = "%s/%s" % (c["engine"], c.get("mode") if c.get("cmd") in ("search", "web", "context") and c["engine"] == "brave" or c.get("cmd") == "search" else c.get("cmd"))
        e = eng.setdefault(k, {"calls": 0, "errors": 0, "lat": [], "cost": 0.0, "ok": 0})
        e["calls"] += 1
        failed = bool(c.get("err")) or c.get("http") != 200
        if failed:
            e["errors"] += 1
        else:
            e["ok"] += 1
            e["lat"].append(c.get("latency_ms") or 0)
        e["cost"] += float(c.get("cost_usd") or 0)
    spend = Counter()
    for c in calls:
        spend[c["engine"]] += float(c.get("cost_usd") or 0)

    def pair_meta(p):
        e = next((c for c in comparable[p] if c["engine"] == "exa"), comparable[p][0])
        return e.get("tag") or "other", e.get("lang") or "?"

    def win_table(keyfn):
        t = defaultdict(lambda: {"exa": 0, "brave": 0, "tie": 0})
        for p, v in cmp_verdicts.items():
            t[keyfn(p)][v.get("winner")] += 1
        rows = []
        for k in sorted(t):
            d = t[k]
            n = d["exa"] + d["brave"] + d["tie"]
            dec = d["exa"] + d["brave"]
            rows.append({"key": k, "exa": d["exa"], "brave": d["brave"], "tie": d["tie"], "n": n,
                         "exa_share": (d["exa"] / dec) if dec else None,
                         "wilson_lb": wilson_lb(d["exa"], dec) if dec else None})
        return rows

    by_tag = win_table(lambda p: pair_meta(p)[0])
    by_lang = win_table(lambda p: pair_meta(p)[1])
    xtab = defaultdict(Counter)
    for v in cmp_verdicts.values():
        xtab[v.get("winner")][v.get("why")] += 1
    overlaps = []
    for p, cs in comparable.items():
        e = next(c for c in cs if c["engine"] == "exa")
        b = next(c for c in cs if c["engine"] == "brave")
        a_, b_ = set(e.get("top_domains") or []), set(b.get("top_domains") or [])
        overlaps.append(len(a_ & b_) / 5.0)
    dom = {"exa": Counter(), "brave": Counter()}
    for c in calls:
        if c["engine"] in dom:
            dom[c["engine"]].update(c.get("top_domains") or [])
    uniq = {e: [(d, n) for d, n in dom[e].most_common() if d not in dom[o]][:10]
            for e, o in (("exa", "brave"), ("brave", "exa"))}
    return {"since": since.isoformat(timespec="seconds"), "generated": now_iso(), "bad_lines": bad,
            "calls": len(calls), "pairs": len(pairs), "comparable": len(comparable), "verdicts": len(cmp_verdicts),
            "spend": dict(spend), "engines": eng, "by_tag": by_tag, "by_lang": by_lang,
            "xtab": {w: dict(c) for w, c in xtab.items()},
            "overlap_mean": (sum(overlaps) / len(overlaps)) if overlaps else None,
            "unique_domains": uniq}


def render_report_md(R):
    L = []
    L.append("# Exa vs Brave — A/B отчёт")
    L.append("")
    L.append("Период: с %s по %s · вызовов %d · пар %d · сравнимых %d · с вердиктом %d (%s)%s"
             % (R["since"][:10], R["generated"][:10], R["calls"], R["pairs"], R["comparable"], R["verdicts"],
                ("%.0f%%" % (100.0 * R["verdicts"] / R["comparable"])) if R["comparable"] else "—",
                (" · битых строк %d" % R["bad_lines"]) if R["bad_lines"] else ""))
    L.append("Расход: " + (" · ".join("%s %s" % (e, fmt_usd(c)) for e, c in sorted(R["spend"].items())) or "—"))
    if R["comparable"] < 20:
        L.append("")
        L.append("> Сравнимых пар %d < 20 — **победителя не называем**, копим данные." % R["comparable"])
    L.append("")
    L.append("## Движки")
    L.append("")
    L.append("| engine/mode | calls | err % | p50 ms | p90 ms | $ total | $/call |")
    L.append("|---|---|---|---|---|---|---|")
    for k in sorted(R["engines"]):
        e = R["engines"][k]
        p50, p90 = pct(e["lat"], 0.5), pct(e["lat"], 0.9)
        L.append("| %s | %d | %.0f%% | %s | %s | %s | %s |" % (
            k, e["calls"], 100.0 * e["errors"] / e["calls"] if e["calls"] else 0,
            "%d" % p50 if p50 is not None else "—", "%d" % p90 if p90 is not None else "—",
            fmt_usd(e["cost"]), fmt_usd(e["cost"] / e["ok"]) if e["ok"] else "—"))
    if not R["engines"]:
        L.append("| — | 0 | — | — | — | — | — |")

    def wt(title, rows):
        L.append("")
        L.append("## Win-rate по %s" % title)
        L.append("")
        L.append("| %s | exa | brave | tie | n | доля exa | Wilson LB 95%% |" % title)
        L.append("|---|---|---|---|---|---|---|")
        if not rows:
            L.append("| — | 0 | 0 | 0 | 0 | нет сравнимых пар | — |")
        for r in rows:
            if r["n"] < 10:
                L.append("| %s | %d | %d | %d | %d | мало данных | — |" % (r["key"], r["exa"], r["brave"], r["tie"], r["n"]))
            else:
                L.append("| %s | %d | %d | %d | %d | %s | %s |" % (
                    r["key"], r["exa"], r["brave"], r["tie"], r["n"],
                    ("%.2f" % r["exa_share"]) if r["exa_share"] is not None else "—",
                    ("%.2f" % r["wilson_lb"]) if r["wilson_lb"] is not None else "—"))

    wt("tag", R["by_tag"])
    wt("lang", R["by_lang"])
    L.append("")
    L.append("## winner × why")
    L.append("")
    L.append("| winner | " + " | ".join(WHY) + " |")
    L.append("|---|" + "---|" * len(WHY))
    for w in ("exa", "brave", "tie"):
        c = R["xtab"].get(w, {})
        L.append("| %s | " % w + " | ".join(str(c.get(x, 0)) for x in WHY) + " |")
    L.append("")
    L.append("## Overlap и уникальные домены")
    L.append("")
    L.append("- Средний overlap top-5 доменов: %s" % (("%.2f" % R["overlap_mean"]) if R["overlap_mean"] is not None else "нет сравнимых пар"))
    for e in ("exa", "brave"):
        u = R["unique_domains"].get(e) or []
        L.append("- Только %s: %s" % (e, ", ".join("%s (%d)" % (d, n) for d, n in u) if u else "—"))
    return "\n".join(L)


def cmd_report(a):
    since = parse_since(a.since)
    R = build_report(since)
    if a.out == "json":
        print(json.dumps(R, ensure_ascii=False, indent=1))
    else:
        print(render_report_md(R))
    return EXIT_OK


# ---------------------------------------------------------------- CLI
def add_common(p, outs=("text", "json", "urls"), default_out="text"):
    p.add_argument("--out", choices=list(outs), default=default_out)
    p.add_argument("--dry-run", action="store_true", help="print request(s) and exit — no HTTP, no key, no log")
    p.add_argument("--no-log", action="store_true", help="do not append to the A/B log")
    p.add_argument("--full", action="store_true", help="lift output caps (titles/snippets/text)")
    p.add_argument("--force", action="store_true", help="bypass the daily soft cap ($%.0f)" % DAILY_CAP_USD)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="per-engine timeout, s (default %d)" % DEFAULT_TIMEOUT)


def build_parser():
    p = Parser(prog="websearch.py", description="Exa + Brave web search with an A/B log (skill /search).")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", metavar="cmd")
    sub.required = True

    e = sub.add_parser("exa", help="Exa /search")
    e.add_argument("query")
    e.add_argument("--tag", required=True, choices=TAGS)
    e.add_argument("--type", default="auto", choices=EXA_TYPES)
    e.add_argument("--category", choices=EXA_CATEGORIES)
    e.add_argument("--include-domains", help="a.com,b.org")
    e.add_argument("--exclude-domains")
    e.add_argument("--start", help="startPublishedDate YYYY-MM-DD")
    e.add_argument("--end", help="endPublishedDate YYYY-MM-DD")
    e.add_argument("-n", type=int, default=10)
    e.add_argument("--contents", default="highlights", choices=["highlights", "text", "summary", "none"])
    e.add_argument("--summary-query")
    e.add_argument("--max-chars", type=int, help="text maxCharacters (with --contents text)")
    e.add_argument("--max-age-hours", type=int, help="crawl freshness: 0 live, -1 cache only")
    e.add_argument("--country", help="userLocation ISO code")
    e.add_argument("--json-patch", help="JSON deep-merged into the body last (systemPrompt, outputSchema, includeText…)")
    add_common(e)

    b = sub.add_parser("brave", help="Brave web/search or llm/context")
    b.add_argument("query")
    b.add_argument("--tag", required=True, choices=TAGS)
    b.add_argument("--mode", default="web", choices=["web", "context"])
    b.add_argument("--country")
    b.add_argument("--lang", help="search_lang, e.g. ru")
    b.add_argument("--freshness", help="pd|pw|pm|py or YYYY-MM-DDtoYYYY-MM-DD")
    b.add_argument("--goggles", action="append", help="goggle URL or inline goggle; repeatable")
    b.add_argument("-n", type=int, default=10)
    b.add_argument("--tokens-brave", type=int, help="llm/context maximum_number_of_tokens (default 8192)")
    b.add_argument("--threshold", choices=["balanced", "strict", "lenient", "disabled"], help="llm/context context_threshold_mode")
    b.add_argument("--json-patch", help="JSON merged into query params")
    add_common(b)

    bo = sub.add_parser("both", help="Exa + Brave in parallel with a shared pair_id")
    bo.add_argument("query")
    bo.add_argument("--tag", required=True, choices=TAGS)
    bo.add_argument("--query-exa", help="separate page-description query for Exa")
    bo.add_argument("-n", type=int, default=8)
    bo.add_argument("--type", default="auto", choices=EXA_TYPES, help="Exa type")
    bo.add_argument("--mode", default="web", choices=["web", "context"], help="Brave mode")
    bo.add_argument("--country")
    bo.add_argument("--lang", help="Brave search_lang")
    bo.add_argument("--no-raw", action="store_true", help="--out json without raw API bodies")
    add_common(bo)

    c = sub.add_parser("contents", help="Exa /contents")
    c.add_argument("urls", nargs="*")
    c.add_argument("--tag", default="other", choices=TAGS)
    g = c.add_mutually_exclusive_group()
    g.add_argument("--text", dest="mode_contents", action="store_const", const="text")
    g.add_argument("--highlights", dest="mode_contents", action="store_const", const="highlights")
    g.add_argument("--summary", dest="mode_contents", action="store_const", const="summary")
    c.add_argument("--summary-query")
    c.add_argument("--max-chars", type=int, default=8000, help="text maxCharacters (default 8000; --full lifts)")
    c.add_argument("--subpages", type=int, help="subpages per URL (start with 5–10)")
    c.add_argument("--subpage-target", help="keywords, comma-separated")
    c.add_argument("--max-age-hours", type=int, help="0 live crawl, -1 cache only, N hours")
    c.add_argument("--livecrawl-timeout", type=int, help="ms (default 12000 when --max-age-hours is set)")
    c.add_argument("--json-patch")
    add_common(c)

    x = sub.add_parser("context", help="Exa /context (Exa Code)")
    x.add_argument("query")
    x.add_argument("--tag", default="code", choices=TAGS)
    x.add_argument("--tokens", default="dynamic", help="dynamic | 50..100000 (5000 good default)")
    x.add_argument("--json-patch")
    add_common(x, outs=("text", "json"))

    v = sub.add_parser("verdict", help="record the model's verdict for a pair")
    v.add_argument("pair_id")
    v.add_argument("winner", choices=["exa", "brave", "tie"])
    v.add_argument("--why", required=True, choices=WHY)
    v.add_argument("--note")
    v.add_argument("--dry-run", action="store_true")
    v.add_argument("--no-log", action="store_true")
    v.add_argument("--force", action="store_true", help="record even if the pair is not in the log")

    r = sub.add_parser("report", help="aggregate the A/B log")
    r.add_argument("--since", default="14d", help="Nd or YYYY-MM-DD (default 14d)")
    r.add_argument("--out", choices=["md", "json"], default="md")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    handlers = {"exa": cmd_exa, "brave": cmd_brave, "both": cmd_both, "contents": cmd_contents,
                "context": cmd_context, "verdict": cmd_verdict, "report": cmd_report}
    try:
        code = handlers[a.cmd](a)
    except BrokenPipeError:
        code = EXIT_OK
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
