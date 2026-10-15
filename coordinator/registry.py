"""Capability registry: fetches each domain's declaration and judges staleness.

The coordinator stamps its own receipt time on every declaration. Domains
never send a timestamp (ADR-0003). A declaration older than the TTL is refused,
so a stale domain can never look like "action not offered".
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

HOST = "127.0.0.1"
CAPABILITIES_PATH = "/capabilities"
DEFAULT_TTL_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 5
MAX_BODY_BYTES = 64 * 1024
EXPECTED_KEYS = frozenset({"domain", "capabilities", "will_not"})


class RegistryError(Exception):
    """Base class for every registry refusal."""


class DomainUnavailable(RegistryError):
    """The domain could not be reached or answered with a non-200 status."""


class DeclarationInvalid(RegistryError):
    """The domain answered, but the declaration is not well formed."""


class DeclarationStale(RegistryError):
    """The stored declaration is older than the TTL."""


class DeclarationMissing(RegistryError):
    """The domain is configured but has never been discovered."""


@dataclass(frozen=True)
class Declaration:
    domain: str
    capabilities: tuple[str, ...]
    will_not: tuple[str, ...]
    received_at: float


def _string_list(value, field):
    if not isinstance(value, list):
        raise DeclarationInvalid(f"{field} must be a list")
    for item in value:
        if not isinstance(item, str) or not item:
            raise DeclarationInvalid(f"{field} items must be non-empty strings")
    if len(set(value)) != len(value):
        raise DeclarationInvalid(f"{field} contains duplicates")
    return value


def _parse_declaration(expected_domain, body, now):
    """Validate a /capabilities body and return a Declaration stamped with now."""
    if len(body) > MAX_BODY_BYTES:
        raise DeclarationInvalid("declaration body is too large")
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise DeclarationInvalid(f"declaration is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != EXPECTED_KEYS:
        raise DeclarationInvalid("declaration must have exactly the expected keys")
    if data["domain"] != expected_domain:
        raise DeclarationInvalid(
            f"expected domain {expected_domain!r}, got {data['domain']!r}")
    capabilities = _string_list(data["capabilities"], "capabilities")
    will_not = _string_list(data["will_not"], "will_not")
    if set(capabilities) & set(will_not):
        raise DeclarationInvalid("capabilities and will_not overlap")
    return Declaration(
        domain=expected_domain,
        capabilities=tuple(sorted(capabilities)),
        will_not=tuple(sorted(will_not)),
        received_at=now,
    )


def _http_get(port, timeout):
    """Return (status, body). A non-2xx status is returned, not raised."""
    # An empty proxy map stops a system proxy from intercepting 127.0.0.1.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://{HOST}:{port}{CAPABILITIES_PATH}"
    try:
        with opener.open(url, timeout=timeout) as response:
            return response.status, response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, b""


class Registry:
    """Holds the latest good declaration for each configured domain."""

    def __init__(self, ports, clock, *, ttl_seconds=DEFAULT_TTL_SECONDS,
                 fetch=None, timeout=HTTP_TIMEOUT_SECONDS):
        for name, port in ports.items():
            if (not isinstance(port, int) or isinstance(port, bool)
                    or not 1 <= port <= 65535):
                raise ValueError(f"invalid port for {name}: {port!r}")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ports = dict(ports)
        self._clock = clock
        self._ttl = ttl_seconds
        self._fetch = fetch or _http_get
        self._timeout = timeout
        self._declarations = {}

    def _port_for(self, domain):
        if domain not in self._ports:
            raise KeyError(f"unknown domain: {domain}")
        return self._ports[domain]

    def refresh(self, domain):
        """Fetch, validate and store the declaration; keep the old one on failure."""
        port = self._port_for(domain)
        try:
            status, body = self._fetch(port, self._timeout)
        except OSError as exc:
            raise DomainUnavailable(f"{domain}: {exc}") from exc
        if status != 200:
            raise DomainUnavailable(f"{domain}: HTTP {status}")
        declaration = _parse_declaration(domain, body, self._clock())
        self._declarations[domain] = declaration
        return declaration

    def refresh_all(self):
        """Refresh every domain in configured order; the first failure propagates."""
        for domain in self._ports:
            self.refresh(domain)

    def _current(self, domain):
        self._port_for(domain)
        declaration = self._declarations.get(domain)
        if declaration is None:
            raise DeclarationMissing(f"{domain}: never discovered")
        age = self._clock() - declaration.received_at
        if age < 0:
            raise DeclarationStale(
                f"{domain}: clock moved backwards, declaration is {-age:.1f}s ahead")
        if age > self._ttl:
            raise DeclarationStale(
                f"{domain}: declaration is {age:.1f}s old, TTL is {self._ttl}s")
        return declaration

    def declaration(self, domain):
        return self._current(domain)

    def will_not(self, domain):
        return self._current(domain).will_not

    def classify(self, domain, action):
        """Return "supported", "will_not" or "unsupported" for one action."""
        declaration = self._current(domain)
        if action in declaration.capabilities:
            return "supported"
        if action in declaration.will_not:
            return "will_not"
        return "unsupported"

    def supports(self, domain, action):
        return self.classify(domain, action) == "supported"
