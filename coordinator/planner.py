"""Planner: one consolidated plan across domains, and its single hash.

build_plan asks the registry for each action's classification, so stale
or unknown domains are refused. Actions on a domain's will_not list stay
in the plan with an advisory warning; they are never dropped. The plan
hash covers the whole plan object (v0.1, ADR-0002).
"""

import hashlib
import json

DOMAIN_ORDER = ("hr", "it", "facilities")
WILL_NOT = "will_not"


def canonical_json(obj):
    """Return the canonical bytes (pure ASCII) of a JSON value.

    Sorted keys, no whitespace, non-ASCII escaped, NaN and Infinity
    rejected so one value has exactly one encoding.
    """
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def plan_hash(plan):
    """Return the SHA-256 hex digest of the canonical encoding of a plan."""
    return hashlib.sha256(canonical_json(plan)).hexdigest()


def build_plan(registry, subject, requests):
    """Build one plan from (domain, action, params) requests.

    Steps are grouped in DOMAIN_ORDER (HR, IT, Facilities); request order
    is kept inside each domain. Unknown domains raise KeyError and stale
    declarations raise DeclarationStale, both from the registry.
    """
    if not isinstance(subject, str) or not subject:
        raise ValueError("subject must be a non-empty string")
    requests = list(requests)
    if not requests:
        raise ValueError("a plan needs at least one action")
    steps = []
    for domain, action, params in requests:
        classification = registry.classify(domain, action)
        if domain not in DOMAIN_ORDER:
            raise ValueError(f"domain {domain!r} is not in the plan order")
        if classification == "unsupported":
            raise ValueError(f"{domain} does not offer {action}")
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        steps.append({
            "domain": domain,
            "action": action,
            "params": params,
            "classification": classification,
        })
    steps.sort(key=lambda step: DOMAIN_ORDER.index(step["domain"]))
    return {"subject": subject, "steps": steps}


def warnings(plan):
    """Return advisory warning strings. Warnings are never part of the hash."""
    found = []
    for step in plan["steps"]:
        if step["classification"] == WILL_NOT:
            found.append(
                f"{step['domain']}: {step['action']} is on the domain's "
                "will_not list; the domain will refuse it, and the plan keeps it"
            )
    return found
