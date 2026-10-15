"""Test child for the provisioner: writes a diagnostic and never prints READY."""

import sys
import threading

sys.stderr.write("bind failed: port in use\n")
sys.stderr.flush()
threading.Event().wait()
