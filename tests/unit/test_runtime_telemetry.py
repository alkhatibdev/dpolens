"""ONNX Runtime's own telemetry is off.

On Linux and macOS, ONNX Runtime reports to Microsoft by default from the moment
it loads: the operating system, the CPU, a persistent device id and the model's
metadata, uploaded from a background thread. An instance that promises to run
offline cannot carry that, so DPOLens switches it off before the runtime loads.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# The runtime stays silent on a CI runner whatever DPOLens does, so these are
# removed to make the test mean the same thing there as on a laptop.
CI_VARIABLES = {
    "CI",
    "TF_BUILD",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "CIRCLECI",
    "TRAVIS",
    "JENKINS_URL",
    "CODEBUILD_BUILD_ID",
    "BUILDKITE",
    "TEAMCITY_VERSION",
    "APPVEYOR",
    "BITBUCKET_BUILD_NUMBER",
    "SYSTEM_TEAMFOUNDATIONCOLLECTIONURI",
    "ORT_RUNNING_UNIT_TESTS",
    "ORT_DISABLE_TELEMETRY",
}


def test_loading_the_runtime_sets_up_no_telemetry(tmp_path: Path) -> None:
    """The runtime keeps its device id and unsent events under the home directory."""
    env = {name: value for name, value in os.environ.items() if name not in CI_VARIABLES}
    env["HOME"] = str(tmp_path)
    env["XDG_CACHE_HOME"] = str(tmp_path / ".cache")

    subprocess.run([sys.executable, "-c", "import dpolens.engine.embedding"], env=env, check=True)

    assert not list(tmp_path.rglob("Microsoft")), "ONNX Runtime set up its telemetry"
