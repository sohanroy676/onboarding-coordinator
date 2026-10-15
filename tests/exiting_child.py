"""Test child for the provisioner: writes a diagnostic and exits before READY."""

import sys

sys.stderr.write("config missing\n")
sys.exit(3)
