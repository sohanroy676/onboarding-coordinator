"""HR domain agent: identity, capabilities, will_not and simulated actions."""

import sys
import time

from domains.domain_agent import DomainSpec, run_agent, simulated_handler

NAME = "hr"
CAPABILITIES = ("create_record", "enroll_benefits")
WILL_NOT = ("change_payroll",)

SPEC = DomainSpec(
    name=NAME,
    capabilities=CAPABILITIES,
    will_not=WILL_NOT,
    handlers={action: simulated_handler(NAME, action) for action in CAPABILITIES},
    port_env="OC_PORT_HR",
    default_port=8101,
)

if __name__ == "__main__":
    sys.exit(run_agent(SPEC, time.time))
