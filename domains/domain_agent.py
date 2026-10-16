"""Shared domain runtime: HTTP server, token check, will_not, ledger write.

This is the only place a token is verified. Each domain process holds
only its own key (OC_DOMAIN_KEY), enforces its own will_not list and is
the only writer of its own ledger.

Endpoints (JSON over HTTP on 127.0.0.1):
    GET  /capabilities -> {"domain", "capabilities", "will_not"}
    POST /execute      -> {"token", "actions": [{"name", "params"?}]}

Token errors are checked in this order: malformed_token,
domain_mismatch, invalid_signature, token_expired, token_replayed.
Each action is then checked in this order: out_of_scope, will_not,
unsupported_action. The ledger line is written before the action runs.
A token is consumed once it passes all token checks.

domains/ must not import from coordinator/, so the canonical JSON
encoding is repeated here.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ledger.ledger import Ledger, LedgerCorrupt

HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024
MAX_TOKEN_CHARS = 4096
MAX_DRAIN_BYTES = 1024 * 1024
LEDGER_NAME = "ledger.jsonl"

_B64URL = re.compile(r"[A-Za-z0-9_-]+")
_CLAIM_STRINGS = ("sub", "act", "aud", "jti", "run_id", "approval_id")
_CLAIM_NAMES = set(_CLAIM_STRINGS) | {"scope", "iat", "exp"}

HTTP_STATUS = {
    "malformed_token": 400,
    "domain_mismatch": 403,
    "invalid_signature": 401,
    "token_expired": 401,
    "token_replayed": 401,
    "approval_replayed": 401,
}


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port that is
    # already in use, which would let an impostor shadow a domain.
    allow_reuse_address = False
    daemon_threads = True


class TokenError(Exception):
    """A token check failed. code is the wire error code."""

    def __init__(self, code, run_id=None):
        super().__init__(code)
        self.code = code
        self.run_id = run_id


@dataclass(frozen=True)
class DomainSpec:
    """Static identity of one domain: what it does and what it refuses."""

    name: str
    capabilities: tuple
    will_not: tuple
    handlers: dict
    port_env: str
    default_port: int

    def __post_init__(self):
        if set(self.capabilities) != set(self.handlers):
            raise ValueError("every capability needs exactly one handler")
        if set(self.capabilities) & set(self.will_not):
            raise ValueError("an action cannot be both supported and will_not")


def simulated_handler(domain, action):
    """Return a handler that only simulates the action (no real system)."""

    def handler(subject, params):
        return {"simulated": True, "domain": domain, "action": action}

    return handler


def _canonical(obj):
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def _unb64(text):
    if not _B64URL.fullmatch(text):
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not base64url") from exc


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_claims(payload):
    """Decode and shape-check the claims; raise ValueError if malformed."""
    claims = json.loads(_unb64(payload).decode("utf-8"))
    if not isinstance(claims, dict) or set(claims) != _CLAIM_NAMES:
        raise ValueError("claims")
    for name in _CLAIM_STRINGS:
        if not isinstance(claims[name], str) or not claims[name]:
            raise ValueError("claims")
    scope = claims["scope"]
    if not isinstance(scope, list) or not scope:
        raise ValueError("claims")
    if not all(isinstance(item, str) and item for item in scope):
        raise ValueError("claims")
    if not _is_int(claims["iat"]) or not _is_int(claims["exp"]):
        raise ValueError("claims")
    return claims


def verify_token(token, domain, key_hex, now, seen_jti, seen_approvals):
    """Return the claims of a valid token or raise TokenError.

    seen_jti and seen_approvals hold the token IDs and approval IDs this domain
    has already executed. This function does not add to them; the caller does.
    """
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
        raise TokenError("malformed_token")
    parts = token.split(".")
    if len(parts) != 2:
        raise TokenError("malformed_token")
    payload, signature = parts
    try:
        claims = _parse_claims(payload)
        presented = _unb64(signature)
    except ValueError as exc:  # includes bad JSON and bad UTF-8
        raise TokenError("malformed_token") from exc
    run_id = claims["run_id"]
    if claims["aud"] != domain:
        raise TokenError("domain_mismatch", run_id)
    expected = hmac.new(
        bytes.fromhex(key_hex), payload.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, presented):
        raise TokenError("invalid_signature", run_id)
    if now >= claims["exp"]:
        raise TokenError("token_expired", run_id)
    if claims["jti"] in seen_jti:
        raise TokenError("token_replayed", run_id)
    if claims["approval_id"] in seen_approvals:
        raise TokenError("approval_replayed", run_id)
    return claims


def _check_actions(actions):
    """Return a list of (name, params), or None if the shape is wrong."""
    if not isinstance(actions, list) or not actions:
        return None
    checked = []
    for item in actions:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        params = item.get("params", {})
        if not isinstance(name, str) or not name or not isinstance(params, dict):
            return None
        checked.append((name, params))
    return checked


class DomainAgent:
    """One domain: verifies tokens, refuses, writes its own ledger."""

    def __init__(self, spec, key_hex, state_dir, clock):
        bytes.fromhex(key_hex)
        self._spec = spec
        self._key_hex = key_hex
        self._clock = clock
        self._ledger_path = Path(state_dir) / spec.name / LEDGER_NAME
        self._ledger = Ledger(self._ledger_path, clock)
        self._lock = threading.Lock()
        self._seen_jti = set()
        self._seen_approvals = set()
        for entry in self._ledger.entries():
            jti = entry["data"].get("jti")
            if jti is not None:
                self._seen_jti.add(jti)
            approval_id = entry["data"].get("approval_id")
            if approval_id is not None:
                self._seen_approvals.add(approval_id)

    @property
    def spec(self):
        return self._spec

    @property
    def ledger_path(self):
        return self._ledger_path

    def capabilities(self):
        return {
            "domain": self._spec.name,
            "capabilities": sorted(self._spec.capabilities),
            "will_not": sorted(self._spec.will_not),
        }

    def execute(self, body):
        """Handle one /execute body; return (http_status, response dict)."""
        if not isinstance(body, dict):
            return 400, {"error": "bad_request"}
        with self._lock:
            return self._execute_locked(body)

    def _execute_locked(self, body):
        try:
            claims = verify_token(
                body.get("token"),
                self._spec.name,
                self._key_hex,
                self._clock(),
                self._seen_jti,
                self._seen_approvals,
            )
        except TokenError as exc:
            return self._reject(exc)
        actions = _check_actions(body.get("actions"))
        if actions is None:
            return 400, {"error": "bad_request"}
        self._seen_jti.add(claims["jti"])
        self._seen_approvals.add(claims["approval_id"])
        results = []
        try:
            for name, params in actions:
                results.append(self._decide_and_act(claims, name, params))
        except OSError:
            return 500, {"error": "ledger_unavailable"}
        return 200, {
            "domain": self._spec.name,
            "run_id": claims["run_id"],
            "results": results,
        }

    def _reject(self, error):
        run_id = error.run_id or "unknown"
        try:
            self._ledger.append(run_id, "token_rejected", {"reason": error.code})
        except OSError:
            return 500, {"error": "ledger_unavailable"}
        return HTTP_STATUS[error.code], {"error": error.code}

    def _refusal_reason(self, claims, name):
        if name not in claims["scope"]:
            return "out_of_scope"
        if name in self._spec.will_not:
            return "will_not"
        if name not in self._spec.handlers:
            return "unsupported_action"
        return None

    def _decide_and_act(self, claims, name, params):
        run_id = claims["run_id"]
        base = {"action": name, "subject": claims["sub"], "jti": claims["jti"],
                "approval_id": claims["approval_id"]}
        reason = self._refusal_reason(claims, name)
        if reason is not None:
            self._ledger.append(run_id, "action_refused", dict(base, reason=reason))
            return {"action": name, "outcome": "refused", "reason": reason}
        self._ledger.append(run_id, "action_executed", base)
        try:
            detail = self._spec.handlers[name](claims["sub"], params)
        except Exception:  # a handler fault must not kill the server
            data = dict(base, reason="handler_error")
            self._ledger.append(run_id, "action_failed", data)
            return {"action": name, "outcome": "failed", "reason": "handler_error"}
        return {"action": name, "outcome": "executed", "detail": detail}


def _make_handler(agent):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OCDomain/0.2"

        def log_message(self, format, *args):
            return  # request lines are not logged; tokens must never leak

        def _send(self, status, payload):
            raw = _canonical(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def _drain(self, length):
            """Discard a refused body (bounded) so the client sees the reply."""
            remaining = min(max(length, 0), MAX_DRAIN_BYTES)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _drain_declared(self):
            """Discard the body of a POST we refuse before reading it."""
            try:
                self._drain(int(self.headers.get("Content-Length", "")))
            except ValueError:
                pass

        def do_GET(self):
            if self.path == "/capabilities":
                self._send(200, agent.capabilities())
            elif self.path == "/execute":
                self._send(405, {"error": "method_not_allowed"})
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self):
            if self.path == "/capabilities":
                self._drain_declared()
                self._send(405, {"error": "method_not_allowed"})
                return
            if self.path != "/execute":
                self._drain_declared()
                self._send(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send(400, {"error": "bad_request"})
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._drain(length)
                self._send(400, {"error": "bad_request"})
                return
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError:
                self._send(400, {"error": "bad_request"})
                return
            status, payload = agent.execute(body)
            self._send(status, payload)

    return Handler


def make_server(agent, host=HOST, port=0):
    """Bind a server for agent; port 0 picks a free port (tests)."""
    if not 0 <= port <= 65535:
        raise ValueError("port out of range")
    return _Server((host, port), _make_handler(agent))


def run_agent(spec, clock):
    """Entry point of a domain process: read env, bind, announce, serve."""
    key_hex = os.environ.get("OC_DOMAIN_KEY", "")
    try:
        if len(key_hex) != 64:
            raise ValueError("wrong length")
        bytes.fromhex(key_hex)
    except ValueError:
        sys.stderr.write("OC_DOMAIN_KEY is missing or not 64 hex digits\n")
        return 2
    state_dir = os.environ.get("OC_STATE_DIR", "state")
    try:
        port = int(os.environ.get(spec.port_env, str(spec.default_port)))
        agent = DomainAgent(spec, key_hex, state_dir, clock)
        server = make_server(agent, HOST, port)
    except (ValueError, OSError, LedgerCorrupt) as exc:
        sys.stderr.write("cannot start %s: %s\n" % (spec.name, exc))
        return 2
    sys.stdout.write("READY %d\n" % server.server_address[1])
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
