"""Facilities domain agent: identity, capabilities, will_not, simulated actions."""

import sys
import time

from domains.domain_agent import DomainSpec, run_agent, simulated_handler

NAME = "facilities"
CAPABILITIES = ("issue_badge", "assign_desk")
WILL_NOT = ("disable_alarm",)

SPEC = DomainSpec(
    name=NAME,
    capabilities=CAPABILITIES,
    will_not=WILL_NOT,
    handlers={action: simulated_handler(NAME, action) for action in CAPABILITIES},
    port_env="OC_PORT_FAC",
    default_port=8103,
)

if __name__ == "__main__":
    sys.exit(run_agent(SPEC, time.time))
