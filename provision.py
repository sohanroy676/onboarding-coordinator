"""Operator: make secrets in memory, start, health-check and stop domains.

Run from the project root with: python provision.py

The exchange secret exists only in this process. Each domain child gets
an explicit environment: a short allowlist of system variables plus its
own key, state directory and port. No child ever sees the exchange
secret or another domain's key.
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from coordinator.tokens import derive_domain_key
from domains import facilities_agent, hr_agent, it_agent

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
READY_TIMEOUT_SECONDS = 15
HEALTH_TIMEOUT_SECONDS = 5
STOP_TIMEOUT_SECONDS = 5
SYSTEM_ENV_ALLOWLIST = ("SYSTEMROOT", "PATH")

AGENTS = (
    ("hr", hr_agent.SPEC, "domains.hr_agent"),
    ("it", it_agent.SPEC, "domains.it_agent"),
    ("facilities", facilities_agent.SPEC, "domains.facilities_agent"),
)


class ProvisionError(Exception):
    """A domain could not be started or failed its health check."""


def _read_ready_line(process, result):
    result.append(process.stdout.readline())


class Provisioner:
    """Starts the three domain processes in order HR, IT, Facilities."""

    def __init__(self, state_dir=None, ports=None, exchange_secret=None,
                 approval_secret=None):
        self._exchange_secret = exchange_secret or secrets.token_hex(32)
        self._approval_secret = approval_secret or secrets.token_hex(32)
        self._state_dir = Path(state_dir) if state_dir else ROOT / "state"
        self._ports = dict(ports or {})
        self._processes = {}
        self.ports = {}

    @property
    def exchange_secret(self):
        """For in-process callers (the coordinator); never printed."""
        return self._exchange_secret

    @property
    def approval_secret(self):
        """For in-process callers (coordinator and approver); never printed."""
        return self._approval_secret

    @property
    def state_dir(self):
        return self._state_dir

    def _child_env(self, name, spec, port):
        env = {}
        for variable in SYSTEM_ENV_ALLOWLIST:
            if variable in os.environ:
                env[variable] = os.environ[variable]
        env["OC_DOMAIN_KEY"] = derive_domain_key(self._exchange_secret, name)
        env["OC_STATE_DIR"] = str(self._state_dir)
        env[spec.port_env] = str(port)
        return env

    def _port_for(self, name, spec):
        if name in self._ports:
            return self._ports[name]
        return int(os.environ.get(spec.port_env, str(spec.default_port)))

    def start(self):
        """Start every domain and health-check it; stop all on failure."""
        try:
            for name, spec, module in AGENTS:
                self._start_one(name, spec, module)
            self.check_health()
        except BaseException:
            self.stop()
            raise
        return dict(self.ports)

    def _start_one(self, name, spec, module):
        port = self._port_for(name, spec)
        process = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=str(ROOT),
            env=self._child_env(name, spec, port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes[name] = process
        line = []
        reader = threading.Thread(target=_read_ready_line, args=(process, line))
        reader.daemon = True
        reader.start()
        reader.join(READY_TIMEOUT_SECONDS)
        text = line[0].strip() if line else ""
        if not text.startswith("READY "):
            detail = ""
            if process.poll() is not None:
                detail = ": " + process.stderr.read().strip()
            raise ProvisionError("%s did not become ready%s" % (name, detail))
        self.ports[name] = int(text.split()[1])

    def check_health(self):
        """GET /capabilities on every domain; raise unless each answers."""
        for name, spec, _module in AGENTS:
            url = "http://%s:%d/capabilities" % (HOST, self.ports[name])
            try:
                with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SECONDS) as r:
                    body = json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, OSError, ValueError) as exc:
                raise ProvisionError("%s failed health check: %s" % (name, exc))
            if body.get("domain") != name:
                raise ProvisionError("%s answered as another domain" % name)

    def stop(self):
        """Terminate every child; kill any that ignore terminate."""
        for process in self._processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self._processes.values():
            try:
                process.wait(STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        self._processes.clear()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop()


def main():
    provisioner = Provisioner()
    try:
        ports = provisioner.start()
    except ProvisionError as exc:
        sys.stderr.write("provision failed: %s\n" % exc)
        return 1
    for name, port in ports.items():
        print("%s healthy on %s:%d" % (name, HOST, port))
    provisioner.stop()
    print("all domains stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
