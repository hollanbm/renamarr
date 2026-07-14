import json
from pathlib import Path
from typing import Any

import yaml


def _load_grafana_dashboard() -> dict[str, Any]:
    return json.loads(
        Path("example/grafana/renamarr-dashboard.v2.json").read_text(encoding="utf-8")
    )


def test_grafana_dashboard_uses_current_metric_names() -> None:
    dashboard = _load_grafana_dashboard()
    dashboard_json = json.dumps(dashboard)

    assert "renamarr_sonarr_rename_items_total" not in dashboard_json
    assert "renamarr_sonarr_folder_rename_items_total" not in dashboard_json
    assert "renamarr_radarr_rename_items_total" not in dashboard_json
    assert "renamarr_radarr_folder_rename_items_total" not in dashboard_json
    assert "renamarr_operation_items_total" in dashboard_json
    assert "renamarr_operation_runs_total" in dashboard_json
    assert "renamarr_arr_command_runs_total" in dashboard_json
    assert "renamarr_job_last_success_seconds" in dashboard_json


def test_grafana_dashboard_uses_v2_json_model() -> None:
    dashboard = _load_grafana_dashboard()

    assert "apiVersion" not in dashboard
    assert "kind" not in dashboard
    assert "metadata" not in dashboard
    assert "spec" not in dashboard
    assert "status" not in dashboard
    assert isinstance(dashboard["annotations"], list)
    assert isinstance(dashboard["elements"], dict)
    assert isinstance(dashboard["layout"], dict)
    assert isinstance(dashboard["links"], list)
    assert isinstance(dashboard["tags"], list)
    assert isinstance(dashboard["timeSettings"], dict)
    assert isinstance(dashboard["title"], str)


def test_grafana_dashboard_layout_references_existing_elements() -> None:
    dashboard = _load_grafana_dashboard()
    element_names = set(dashboard["elements"])
    layout_element_names = {
        item["spec"]["element"]["name"]
        for tab in dashboard["layout"]["spec"]["tabs"]
        for item in tab["spec"]["layout"]["spec"]["items"]
    }

    assert layout_element_names == element_names


def test_grafana_dashboard_panel_ids_are_unique() -> None:
    dashboard = _load_grafana_dashboard()

    panel_ids = [element["spec"]["id"] for element in dashboard["elements"].values()]

    assert len(panel_ids) == len(set(panel_ids))


def test_grafana_dashboard_has_instance_name_variable_defaulting_to_all() -> None:
    dashboard = _load_grafana_dashboard()
    variables = {
        variable["spec"]["name"]: variable for variable in dashboard["variables"]
    }

    instance_name = variables["instance_name"]
    spec = instance_name["spec"]

    assert instance_name["kind"] == "QueryVariable"
    assert spec["allValue"] == ".*"
    assert spec["current"] == {
        "selected": True,
        "text": "All",
        "value": "$__all",
    }
    assert spec["includeAll"] is True
    assert spec["label"] == "Instance name"
    assert spec["multi"] is False
    assert spec["query"]["group"] == "prometheus"
    assert (
        spec["query"]["spec"]["query"] == "label_values(renamarr_job_runs_total, name)"
    )


def test_grafana_dashboard_prometheus_queries_use_instance_name_variable() -> None:
    dashboard = _load_grafana_dashboard()

    prometheus_expressions = [
        query["spec"]["query"]["spec"]["expr"]
        for element in dashboard["elements"].values()
        for query in element["spec"]["data"]["spec"]["queries"]
        if query["spec"]["query"]["group"] == "prometheus"
    ]

    assert len(prometheus_expressions) == 13
    assert all('name=~"$instance_name"' in expr for expr in prometheus_expressions)


def test_grafana_dashboard_tempo_metric_queries_let_grafana_choose_step() -> None:
    dashboard = _load_grafana_dashboard()

    tempo_metric_queries = [
        query_spec
        for element in dashboard["elements"].values()
        for query in element["spec"]["data"]["spec"]["queries"]
        if query["spec"]["query"]["group"] == "tempo"
        for query_spec in [query["spec"]["query"]["spec"]]
        if query_spec.get("metricsQueryType") == "range"
    ]

    assert len(tempo_metric_queries) == 2
    assert all("step" not in query_spec for query_spec in tempo_metric_queries)


def test_grafana_dashboard_tempo_metric_panels_limit_time_range() -> None:
    dashboard = _load_grafana_dashboard()

    tempo_metric_panel_query_options = {
        name: element["spec"]["data"]["spec"]["queryOptions"]
        for name, element in dashboard["elements"].items()
        if any(
            query["spec"]["query"]["group"] == "tempo"
            and query["spec"]["query"]["spec"].get("metricsQueryType") == "range"
            for query in element["spec"]["data"]["spec"]["queries"]
        )
    }

    assert tempo_metric_panel_query_options == {
        "panel-error-trace-rate": {"timeFrom": "24h"},
        "panel-span-rate": {"timeFrom": "24h"},
    }


def test_grafana_dashboard_grid_items_do_not_overlap() -> None:
    dashboard = _load_grafana_dashboard()

    for tab in dashboard["layout"]["spec"]["tabs"]:
        occupied_cells: set[tuple[int, int]] = set()
        for item in tab["spec"]["layout"]["spec"]["items"]:
            item_spec = item["spec"]
            x = item_spec["x"]
            y = item_spec["y"]
            width = item_spec["width"]
            height = item_spec["height"]
            cells = {
                (column, row)
                for column in range(x, x + width)
                for row in range(y, y + height)
            }

            assert x >= 0
            assert y >= 0
            assert width > 0
            assert height > 0
            assert x + width <= 24
            assert occupied_cells.isdisjoint(cells)

            occupied_cells.update(cells)


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
