import json
from pathlib import Path

import yaml


def test_grafana_dashboard_uses_current_metric_names() -> None:
    dashboard = json.loads(
        Path("example/grafana/renamarr-dashboard.v2.json").read_text(encoding="utf-8")
    )
    dashboard_json = json.dumps(dashboard)

    assert "renamarr_sonarr_rename_items_total" not in dashboard_json
    assert "renamarr_sonarr_folder_rename_items_total" not in dashboard_json
    assert "renamarr_radarr_rename_items_total" not in dashboard_json
    assert "renamarr_radarr_folder_rename_items_total" not in dashboard_json
    assert "renamarr_operation_items_total" in dashboard_json
    assert "renamarr_operation_runs_total" in dashboard_json
    assert "renamarr_arr_command_runs_total" in dashboard_json
    assert "renamarr_job_last_success_seconds" in dashboard_json


def test_grafana_alert_examples_are_valid_yaml() -> None:
    alerts = yaml.safe_load(
        Path("example/grafana/renamarr-alerts.yaml").read_text(encoding="utf-8")
    )

    alert_names = {
        rule["alert"] for group in alerts["groups"] for rule in group["rules"]
    }

    assert alert_names == {
        "RenamarrJobStale",
        "RenamarrJobFailed",
        "RenamarrArrCommandFailed",
        "RenamarrOperationFailed",
        "RenamarrJobDurationHigh",
    }
