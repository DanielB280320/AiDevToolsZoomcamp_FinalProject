"""`otelcol validate` on the collector configs the hosts load (#130 AC 5).

prod / local load `config.yaml`; dev (OBS_MODE=forward) loads `config.yaml` + `config.forward.yaml`.
Skipped when Docker or the pinned collector image is not available locally.
"""

import pytest

from tests.unit.test_collector_hardening_runtime import CONFIG, IMAGE, _docker, _image_available

pytestmark = pytest.mark.skipif(not _image_available(), reason="docker / collector image missing")

COLLECTOR_DIR = CONFIG.parent


@pytest.mark.parametrize(
    "configs",
    [["config.yaml"], ["config.yaml", "config.forward.yaml"]],
    ids=["prod", "dev-forward"],
)
def test_otelcol_validate_passes(configs: list[str]) -> None:
    run = _docker(
        "run", "--rm",
        "-e", "FITWISE_ENV=x",
        "-e", "OTLP_UPSTREAM_ENDPOINT=h:4317",
        "-v", f"{COLLECTOR_DIR}:/c:ro",
        IMAGE, "validate", *[f"--config=/c/{name}" for name in configs],
    )  # fmt: skip
    assert run.returncode == 0, run.stderr[-2000:]
