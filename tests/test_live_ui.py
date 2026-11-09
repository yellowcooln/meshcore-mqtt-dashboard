import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["burst", "hidden", "stable", "cadence"])
def test_live_dashboard_batches_without_losing_updates(mode):
  harness = Path(__file__).with_name("live_ui_harness.cjs")
  subprocess.run(["node", str(harness), mode], check=True, capture_output=True, text=True)
