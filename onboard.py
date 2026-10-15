"""Onboard one new hire from the console: plan, approve, run, rebuild.

Run from the project root with: python onboard.py --subject <id>

The flow lives in app/onboarding.py. Exit codes:
    0  every action executed (status success)
    1  partial, failed or aborted run, or an interrupted run
    2  bad input, or the plan was refused before any approval prompt
    3  not approved (answer other than y, end of input, or Ctrl-C)
    4  the domains did not start or did not give a valid declaration
"""

import argparse
import sys

from app.onboarding import run_onboarding


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python onboard.py",
        description="Plan, approve at the console, run and rebuild one onboarding.",
    )
    parser.add_argument("--subject", required=True,
                        help="the new hire's identifier: one ASCII token with one @")
    parser.add_argument("--request", action="append", metavar="DOMAIN:ACTION",
                        help="a request such as it:create_account; repeat for several. "
                             "When given, these replace the six default requests.")
    args = parser.parse_args(argv)
    return run_onboarding(args.subject, args.request)


if __name__ == "__main__":
    sys.exit(main())
