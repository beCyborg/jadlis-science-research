#!/usr/bin/env python3
"""stdio <-> Streamable HTTP relay for one MCP server (stdlib only, Python 3.9+).

Started by scripts/mcp-run when the plugin's *_mcp_url option points at a shared
MCP daemon. Claude Code talks stdio to this process; every JSON-RPC line is POSTed
to the daemon and the reply (JSON or SSE) is written back as one line.

Env:
  JADLIS_MCP_URL     Streamable HTTP endpoint of the shared server (required)
  JADLIS_MCP_BEARER  optional bearer token (kept out of argv on purpose: argv is visible in ps)

Recovery: when the daemon restarts, its session id goes stale and it answers 404.
The relay then replays the cached initialize handshake once and retries the request.
Not supported: server-initiated messages over the GET stream (list_changed etc.).
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request

URL = os.environ.get("JADLIS_MCP_URL", "")
BEARER = os.environ.get("JADLIS_MCP_BEARER", "")
TIMEOUT = 1800  # seconds; stdio servers have no per-request timer in Claude Code

state = {"sid": None, "init": None, "initialized": None}
out_lock = threading.Lock()
sid_lock = threading.Lock()


def emit(text):
    with out_lock:
        sys.stdout.write(text.rstrip("\n") + "\n")
        sys.stdout.flush()


def post(line, sid):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    if BEARER:
        headers["Authorization"] = "Bearer " + BEARER
    req = urllib.request.Request(URL, data=line.encode(), headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def read_reply(resp):
    """Yield JSON-RPC message strings from a JSON or SSE response."""
    ctype = resp.headers.get("Content-Type", "")
    if resp.status == 202:
        return
    if "text/event-stream" in ctype:
        data = []
        for raw in resp:
            s = raw.decode().rstrip("\r\n")
            if s.startswith("data:"):
                data.append(s[5:].lstrip())
            elif s == "" and data:
                yield "\n".join(data)
                data = []
        if data:
            yield "\n".join(data)
    else:
        body = resp.read().decode()
        if body.strip():
            yield body


def reinitialize():
    """Replay the cached handshake after the daemon dropped our session."""
    with sid_lock:
        state["sid"] = None
        if not state["init"]:
            return
        with post(state["init"], None) as r:
            state["sid"] = r.headers.get("Mcp-Session-Id")
            for _ in read_reply(r):
                pass
        if state["initialized"]:
            with post(state["initialized"], state["sid"]) as r:
                for _ in read_reply(r):
                    pass


def handle(line, msg):
    for attempt in (1, 2):
        try:
            with post(line, state["sid"]) as r:
                if msg.get("method") == "initialize":
                    state["sid"] = r.headers.get("Mcp-Session-Id")
                for reply in read_reply(r):
                    emit(reply)
            return
        except urllib.error.HTTPError as e:
            if e.code == 404 and attempt == 1 and msg.get("method") != "initialize":
                try:
                    reinitialize()
                    continue
                except Exception as e2:  # daemon still down
                    err = e2
            else:
                err = e
        except Exception as e:
            err = e
        if msg.get("id") is not None:
            emit(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                             "error": {"code": -32000, "message": "mcp-relay: %s" % err}}))
        return


def main():
    if not URL:
        sys.stderr.write("mcp-relay: JADLIS_MCP_URL is empty\n")
        sys.exit(2)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        if method == "initialize":
            state["init"] = line
            handle(line, msg)  # synchronous: later requests need the session id
        elif method == "notifications/initialized":
            state["initialized"] = line
            handle(line, msg)
        else:
            threading.Thread(target=handle, args=(line, msg), daemon=True).start()


if __name__ == "__main__":
    main()
