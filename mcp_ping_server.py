#!/usr/bin/env python3
"""Dead-simple MCP ping server for diagnosing stdio transport issues."""
import json
import sys
import os
import re

LOG = open("/tmp/mcp-ping-debug.log", "a")

def log(msg):
    LOG.write(f"[pid={os.getpid()}] {msg}\n")
    LOG.flush()

def send(response):
    body = json.dumps(response, separators=(",", ":"))
    log(f"SEND: {body[:200]}")
    sys.stdout.buffer.write(body.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()

def read_request():
    log("RECV: waiting for line...")
    line = sys.stdin.buffer.readline()
    if not line:
        log("RECV: EOF")
        return None
    line = line.strip()
    if not line:
        log("RECV: empty line, skipping")
        return read_request()
    parsed = json.loads(line)
    log(f"RECV: method={parsed.get('method')} id={parsed.get('id')}")
    return parsed

def main():
    log("START")
    log(f"  python={sys.executable}")
    log(f"  stdin isatty={sys.stdin.isatty()}")
    log(f"  stdout isatty={sys.stdout.isatty()}")

    while True:
        req = read_request()
        if req is None:
            log("EXIT (null request)")
            break

        method = req.get("method", "")
        rid = req.get("id")

        if method == "initialize":
            client_version = req.get("params", {}).get("protocolVersion", "unknown")
            log(f"INIT: client wants protocolVersion={client_version}, full params={json.dumps(req.get('params', {}))}")
            SUPPORTED = ["2025-03-26", "2024-11-05"]
            negotiated = client_version if client_version in SUPPORTED else SUPPORTED[0]
            log(f"INIT: negotiated protocolVersion={negotiated}")
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mcp-ping", "version": "0.0.1"},
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"tools": [{
                    "name": "ping",
                    "description": "Returns pong.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []},
                }]},
            })
        elif method == "tools/call":
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": [{"type": "text", "text": "pong"}]},
            })
        else:
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"unknown: {method}"},
            })

    log("DONE")

if __name__ == "__main__":
    main()
