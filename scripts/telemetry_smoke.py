"""Exercise OTel and native wheels inside the final hardened runtime."""

import json
import os
import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import psutil
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from renamarr.models.media import FileRenameBatch
from renamarr.radarr.radarr_adapter import RadarrAdapter
from renamarr.sonarr.sonarr_adapter import SonarrAdapter
from renamarr.telemetry import Telemetry


def main() -> None:
    """Verify HTTPS export, client instrumentation, process metrics, and flushing."""
    received: dict[str, list[bytes]] = {}

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Return a minimal Arr media listing."""
            body = json.dumps(
                [{"id": 1, "title": "Smoke title", "path": "/media/Smoke title"}]
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            """Accept a command or OTLP export."""
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.setdefault(self.path, []).append(body)
            response = b'{"id": 17}' if self.path == "/api/v3/command" else b""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            """Keep successful smoke checks quiet."""

    certificate = Path(os.environ["SMOKE_CERTIFICATE"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, os.environ["SMOKE_PRIVATE_KEY"])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    try:
        try:
            with (
                socket.create_connection(("localhost", port)) as connection,
                ssl.create_default_context().wrap_socket(
                    connection, server_hostname="localhost"
                ),
            ):
                raise AssertionError("Untrusted collector certificate was accepted")
        except ssl.SSLCertVerificationError:
            pass
        endpoint = f"https://localhost:{port}"
        os.environ.update(
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
                "OTEL_EXPORTER_OTLP_CERTIFICATE": str(certificate),
                "OTEL_METRIC_EXPORT_INTERVAL": "3600000",
                "OTEL_BSP_SCHEDULE_DELAY": "3600000",
                "SSL_CERT_FILE": str(certificate),
            }
        )
        telemetry = Telemetry()
        secret = "smoke-api-key-never-export"
        telemetry.redactor.register(secret)
        try:
            for service, adapter_type in (
                ("sonarr", SonarrAdapter),
                ("radarr", RadarrAdapter),
            ):
                workflow = telemetry.workflow(service, "smoke")
                with workflow.operation("scan", "run"):
                    adapter = adapter_type(endpoint, secret)
                    try:
                        items = adapter.list_media_items()
                        assert items[0].title == "Smoke title"
                        assert (
                            adapter.start_file_rename(
                                FileRenameBatch((1,), (100,), "Smoke title")
                            )
                            == 17
                        )
                    finally:
                        adapter.close()
        finally:
            telemetry.shutdown()
        assert psutil.Process().memory_info().rss > 0
        metric_names = set()
        http_instances = set()
        for payload in received["/v1/metrics"]:
            decoded = ExportMetricsServiceRequest.FromString(payload)
            metric_names.update(
                m.name
                for r in decoded.resource_metrics
                for s in r.scope_metrics
                for m in s.metrics
            )
            for resource in decoded.resource_metrics:
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        if metric.name == "http.client.duration":
                            for point in metric.histogram.data_points:
                                http_instances.update(
                                    attribute.value.string_value
                                    for attribute in point.attributes
                                    if attribute.key == "arr.service"
                                )
            assert secret not in str(decoded)
        assert {
            "process.cpu.time",
            "process.memory.usage",
            "process.thread.count",
            "renamarr.scan.count",
        } <= metric_names
        assert http_instances == {"sonarr", "radarr"}
        spans = [
            span
            for payload in received["/v1/traces"]
            for r in ExportTraceServiceRequest.FromString(payload).resource_spans
            for s in r.scope_spans
            for span in s.spans
        ]
        assert len([span for span in spans if span.name == "renamarr.scan.run"]) == 2
        bodies = [
            a.value.string_value
            for span in spans
            for a in span.attributes
            if a.key == "http.request.body"
        ]
        assert len(bodies) == 2
        payloads = [json.loads(body) for body in bodies]
        assert payloads[0]["files"] == [100]
        assert payloads[1]["movieIds"] == [1]
        assert all(secret not in str(span) for span in spans)
        assert all(
            "/v1/traces" not in str(span) and "/v1/metrics" not in str(span)
            for span in spans
        )
        print(
            f"PASS: psutil {psutil.__version__}, HTTPS OTLP, both Arr clients, {len(spans)} spans, {len(metric_names)} metrics, UID {os.getuid()}"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
