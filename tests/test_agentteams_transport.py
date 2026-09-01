from __future__ import annotations

from contextlib import contextmanager
import base64
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any, Iterator
import urllib.parse

import pytest

import visiondata_gate.agentteams_transport as agentteams_transport
from visiondata_gate.agentteams_transport import (
    AgentTeamsTransportMode,
    HostedAgentTeamsConfig,
    HostedAgentTeamsTransport,
    HostedProjectSubmission,
    hosted_agentteams_from_environment,
    verify_hosted_agentteams_receipt,
)
from visiondata_gate.agentteams_v122 import build_skill_distribution_plan
from visiondata_gate.evidence import canonical_json_bytes, sha256_bytes
from tools.agentteams_v122_bridge import main as bridge_main


def _assignments() -> dict[str, list[str]]:
    rows = build_skill_distribution_plan()["worker_assignments"]
    return {
        str(row["worker"]): list(row["skills"]) for row in rows if isinstance(row, dict)
    }


def _team_payload() -> dict[str, Any]:
    workers = sorted(_assignments())
    return {
        "name": "visiondata-gate",
        "phase": "Active",
        "workerMembers": [
            {
                "name": name,
                "role": (
                    "team_leader" if name == "visiondata-release-lead" else "worker"
                ),
            }
            for name in workers
        ],
        "leaderName": "visiondata-release-lead",
        "teamRoomID": "!team:matrix.test",
        "leaderDMRoomID": "!leader-dm:matrix.test",
        "leaderReady": True,
        "readyWorkers": len(workers),
        "totalWorkers": len(workers),
    }


def _worker_payload() -> dict[str, Any]:
    assignments = _assignments()
    workers = [
        {
            "name": name,
            "phase": "Running",
            "skills": skills,
            "containerState": "Running",
            "matrixUserID": f"@{name}:matrix.test",
            "roomID": f"!{name}:matrix.test",
            "team": "visiondata-gate",
            "role": ("team_leader" if name == "visiondata-release-lead" else "worker"),
        }
        for name, skills in sorted(assignments.items())
    ]
    return {"workers": workers, "total": len(workers)}


class _AgentTeamsHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        assert isinstance(payload, dict)
        return payload

    def _count(self) -> None:
        key = f"{self.command} {self.path}"
        self.server.counts[key] = self.server.counts.get(key, 0) + 1

    def do_GET(self) -> None:
        self._count()
        if self.headers.get("Authorization") != "Bearer controller-secret":
            self._json(401, {"error": "unauthorized"})
            return
        if self.path == "/api/v1/version":
            payload = {"controller": self.server.version_controller}
            payload.update(self.server.version_extra)
            if self.server.controller_echo_token:
                payload["echo"] = "controller-secret"
            self._json(200, payload)
            return
        if self.path == "/api/v1/teams/visiondata-gate":
            self._json(200, self.server.team_payload)
            return
        if self.path == "/api/v1/workers":
            self._json(200, self.server.worker_payload)
            return
        if self.path.startswith("/api/v1/projects/") and self.path.endswith(
            "/workflow"
        ):
            if self.server.project is None:
                self._json(404, {"error": "project not found"})
                return
            ingress_observed = bool(self.server.matrix_events)
            self._json(
                200,
                {
                    **self.server.project,
                    "nodes": [
                        {
                            "id": self.server.workflow_node_id,
                            "name": self.server.workflow_node_name,
                            "status": (
                                self.server.workflow_status
                                if ingress_observed
                                else "pending"
                            ),
                            "assignee": self.server.workflow_assignee,
                        }
                    ],
                    "next": ["audit-evidence"],
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._count()
        if self.headers.get("Authorization") != "Bearer controller-secret":
            self._json(401, {"error": "unauthorized"})
            return
        if self.path != "/api/v1/projects":
            self._json(404, {"error": "not found"})
            return
        if self.server.project_fail_status is not None:
            self._json(
                self.server.project_fail_status,
                {"error": "injected project failure"},
            )
            return
        request = self._body()
        if self.server.project is not None:
            self._json(409, {"error": "project already exists"})
            return
        self.server.project = {
            "project_id": request["project_id"],
            "title": request["title"],
            "status": "active",
            "team_id": request["team_id"],
            "plan_type": "dag",
        }
        self._json(201, self.server.project)

    def do_PUT(self) -> None:
        self._count()
        if self.headers.get("Authorization") != "Bearer matrix-secret":
            self._json(401, {"error": "unauthorized"})
            return
        if "/_matrix/client/v3/rooms/" not in self.path:
            self._json(404, {"error": "not found"})
            return
        request = self._body()
        assert request["m.mentions"]["user_ids"] == [
            "@visiondata-release-lead:matrix.test"
        ]
        txn_id = urllib.parse.unquote(self.path.rsplit("/", 1)[-1])
        self.server.matrix_attempts[txn_id] = (
            self.server.matrix_attempts.get(txn_id, 0) + 1
        )
        if self.server.matrix_fail_once and self.server.matrix_attempts[txn_id] == 1:
            self._json(503, {"error": "injected matrix failure"})
            return
        event_id = self.server.matrix_events.setdefault(
            txn_id,
            self.server.matrix_event_id
            or f"$event-{len(self.server.matrix_events) + 1}",
        )
        response = {"event_id": event_id}
        if self.server.matrix_echo_token:
            response["echo"] = "matrix-secret"
        self._json(200, response)


@contextmanager
def _server() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AgentTeamsHandler)
    server.counts = {}
    server.project = None
    server.matrix_events = {}
    server.matrix_attempts = {}
    server.matrix_fail_once = False
    server.project_fail_status = None
    server.controller_echo_token = False
    server.matrix_echo_token = False
    server.version_controller = "dev"
    server.version_extra = {}
    server.workflow_status = "completed"
    server.workflow_node_id = "audit-evidence"
    server.workflow_node_name = "Audit evidence"
    server.workflow_assignee = "@visiondata-image-quality:matrix.test"
    server.matrix_event_id = None
    server.team_payload = _team_payload()
    server.worker_payload = _worker_payload()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _transport(
    root: str,
    *,
    mode: AgentTeamsTransportMode = AgentTeamsTransportMode.SHADOW,
    write_enabled: bool = False,
    read_max_retries: int = 0,
) -> HostedAgentTeamsTransport:
    return HostedAgentTeamsTransport(
        HostedAgentTeamsConfig(
            mode=mode,
            controller_base_url=root,
            controller_allowed_hosts=["127.0.0.1"],
            controller_allow_local=True,
            matrix_base_url=root,
            matrix_allowed_hosts=["127.0.0.1"],
            matrix_allow_local=True,
            write_enabled=write_enabled,
            timeout_seconds=1,
            read_max_retries=read_max_retries,
            poll_timeout_seconds=0.2,
            poll_interval_seconds=0.01,
        ),
        controller_token="controller-secret",
        matrix_token="matrix-secret",
    )


def _resign_receipt(path: Path, payload: dict[str, Any]) -> None:
    stable = copy.deepcopy(payload)
    stable.pop("receipt_sha256", None)
    payload["receipt_sha256"] = sha256_bytes(canonical_json_bytes(stable))
    path.write_bytes(canonical_json_bytes(payload))


def _submission(*, wait_for_remote_execution: bool = False) -> HostedProjectSubmission:
    return HostedProjectSubmission(
        source_run_id="run-hosted-contract",
        title="Vision dataset release audit",
        goal="Inspect the governed batch and return evidence-bound findings.",
        project_id="vdg-hosted-contract-test",
        wait_for_remote_execution=wait_for_remote_execution,
    )


def test_environment_defaults_off_and_requires_explicit_credential_gate() -> None:
    assert hosted_agentteams_from_environment({}) is None
    with pytest.raises(PermissionError, match="suppressed"):
        hosted_agentteams_from_environment(
            {
                "VISIONDATA_AGENTTEAMS_MODE": "shadow",
                "VISIONDATA_AGENTTEAMS_BASE_URL": "https://controller.example",
                "VISIONDATA_AGENTTEAMS_ALLOWED_HOSTS": "controller.example",
                "VISIONDATA_AGENTTEAMS_AUTH_TOKEN": "real-looking-token",
            }
        )


def test_config_rejects_url_credentials_and_matrix_without_allowlist() -> None:
    with pytest.raises(ValueError, match="credentials"):
        HostedAgentTeamsConfig(
            mode="shadow",
            controller_base_url=("https://user:secret" + "@" + "controller.example"),
            controller_allowed_hosts=["controller.example"],
        )
    with pytest.raises(ValueError, match="matrix_allowed_hosts"):
        HostedAgentTeamsConfig(
            mode="shadow",
            controller_base_url="https://controller.example",
            controller_allowed_hosts=["controller.example"],
            matrix_base_url="https://matrix.example",
        )


def test_shadow_probe_writes_verified_allowlisted_projections_without_secrets(
    tmp_path: Path,
) -> None:
    with _server() as (server, root):
        transport = _transport(root)
        receipt = transport.collect_runtime_evidence(tmp_path / "probe")
        counts = dict(server.counts)
        with pytest.raises(FileExistsError):
            transport.collect_runtime_evidence(tmp_path / "probe")
        assert server.counts == counts

    assert receipt.status == "PASS"
    assert receipt.operation_status == "CONTROL_PLANE_READY"
    assert receipt.controller_connected is True
    assert receipt.team_ready is True
    assert receipt.workers_ready is True
    assert receipt.skill_specs_verified is True
    assert receipt.skill_files_verified is False
    assert receipt.hosted_runtime_verified is False
    assert receipt.local_runtime_connection_status == "mapped_not_connected"
    assert receipt.schema_version == "visiondata-gate.agentteams-hosted-receipt.v2"
    assert receipt.evidence_mode == "allowlisted_projection"
    assert receipt.exact_wire_retained is False
    assert receipt.opaque_remote_values_retained is False
    assert set(receipt.evidence_projections) == {"version", "team", "workers"}
    assert not (tmp_path / "probe" / "agentteams_hosted_raw").exists()
    validation = verify_hosted_agentteams_receipt(
        tmp_path / "probe" / "agentteams_hosted_receipt.json"
    )
    assert validation.status == "PASS"
    assert validation.checks["allowlisted_projection_mode"] is True
    assert validation.checks["exact_wire_not_retained"] is True
    bundle = b"".join(
        path.read_bytes() for path in (tmp_path / "probe").rglob("*") if path.is_file()
    )
    assert b"controller-secret" not in bundle
    assert b"matrix-secret" not in bundle


def test_gated_submit_registers_project_and_uses_idempotent_matrix_ingress(
    tmp_path: Path,
) -> None:
    request = HostedProjectSubmission(
        source_run_id="run-20260828",
        title="Vision dataset release audit",
        goal="Inspect the governed batch and return evidence-bound findings.",
        project_id="vdg-hosted-contract-test",
        wait_for_remote_execution=True,
    )
    with _server() as (server, root):
        transport = _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        )
        first = transport.submit_project(
            tmp_path / "first",
            request,
            approval_id="approval-hosted-001",
        )
        second = transport.submit_project(
            tmp_path / "second",
            request,
            approval_id="approval-hosted-001",
        )
        changed_approval = transport.submit_project(
            tmp_path / "changed-approval",
            request,
            approval_id="approval-hosted-002",
        )

    assert first.status == "PASS"
    assert first.project_registered is True
    assert first.leader_ingress_sent is True
    assert first.workflow_observed is True
    assert first.remote_task_execution_observed is True
    assert first.operation_status == "REMOTE_EXECUTION_OBSERVED"
    assert first.matrix_assignment_verified is False
    assert first.hosted_runtime_verified is False
    assert second.matrix_transaction_sha256 == first.matrix_transaction_sha256
    assert changed_approval.matrix_transaction_sha256 != (
        first.matrix_transaction_sha256
    )
    assert first.leader_ingress_event_id is None
    assert len(server.matrix_events) == 2
    assert server.counts["POST /api/v1/projects"] == 1
    assert (
        verify_hosted_agentteams_receipt(
            tmp_path / "first" / "agentteams_hosted_receipt.json"
        ).status
        == "PASS"
    )


@pytest.mark.parametrize(
    ("workflow_status", "execution_observed"),
    [
        ("pending", False),
        ("delegated", False),
        ("blocked", False),
        ("revision", False),
        ("in-progress", True),
        ("completed", True),
    ],
)
def test_workflow_status_has_strict_execution_evidence_boundary(
    tmp_path: Path,
    workflow_status: str,
    execution_observed: bool,
) -> None:
    output = tmp_path / workflow_status
    with _server() as (server, root):
        server.workflow_status = workflow_status
        receipt = _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        ).submit_project(
            output,
            _submission(),
            approval_id="approval-status-boundary",
        )

    assert receipt.remote_task_execution_observed is execution_observed
    assert receipt.operation_status == (
        "REMOTE_EXECUTION_OBSERVED" if execution_observed else "LEADER_INGRESS_SENT"
    )
    assert (
        verify_hosted_agentteams_receipt(
            output / "agentteams_hosted_receipt.json"
        ).status
        == "PASS"
    )


def test_wait_for_execution_is_not_satisfied_by_delegation(tmp_path: Path) -> None:
    output = tmp_path / "delegated"
    with _server() as (server, root):
        server.workflow_status = "delegated"
        receipt = _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        ).submit_project(
            output,
            _submission(wait_for_remote_execution=True),
            approval_id="approval-delegated-is-not-execution",
        )

    assert receipt.status == "PARTIAL"
    assert receipt.remote_task_execution_observed is False
    assert receipt.operation_status == "LEADER_INGRESS_SENT"
    assert "No in-progress/completed workflow node" in " ".join(receipt.reasons)
    assert server.counts["GET /api/v1/projects/vdg-hosted-contract-test/workflow"] > 2
    assert (
        verify_hosted_agentteams_receipt(
            output / "agentteams_hosted_receipt.json"
        ).status
        == "PASS"
    )


def test_controller_token_echo_is_rejected_without_remote_value_persistence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "controller-echo"
    with _server() as (server, root):
        server.controller_echo_token = True
        receipt = _transport(root).collect_runtime_evidence(output)

    assert receipt.status == "FAIL"
    assert "controller-secret" not in receipt.model_dump_json()
    bundle = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file())
    assert b"controller-secret" not in bundle
    assert not (output / "agentteams_hosted_raw").exists()


def test_matrix_token_echo_refuses_all_raw_persistence(tmp_path: Path) -> None:
    output = tmp_path / "matrix-echo"
    with _server() as (server, root):
        server.matrix_echo_token = True
        with pytest.raises(RuntimeError, match="schema rejected") as captured:
            _transport(
                root,
                mode=AgentTeamsTransportMode.GATED,
                write_enabled=True,
            ).submit_project(
                output,
                _submission(),
                approval_id="approval-matrix-secret-echo",
            )

    assert "matrix-secret" not in str(captured.value)
    assert not [path for path in output.rglob("*") if path.is_file()]


@pytest.mark.parametrize(
    "encoded",
    [
        base64.b64encode(b"controller-secret").decode("ascii"),
        b"controller-secret".hex(),
        "controller%2Dsecret",
    ],
)
def test_reversibly_encoded_values_in_known_fields_are_never_persisted(
    tmp_path: Path,
    encoded: str,
) -> None:
    output = tmp_path / sha256_bytes(encoded.encode("utf-8"))[:12]
    with _server() as (server, root):
        server.version_controller = encoded
        server.team_payload["teamRoomID"] = f"!{encoded}"
        server.team_payload["leaderDMRoomID"] = f"!{encoded}"
        server.worker_payload["workers"][0]["skills"].append(encoded)
        server.workflow_node_id = encoded
        server.workflow_node_name = encoded
        server.workflow_assignee = encoded
        server.matrix_event_id = f"${encoded}"
        receipt = _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        ).submit_project(
            output,
            _submission(),
            approval_id="approval-encoded-remote-values",
        )

    assert receipt.status == "PASS"
    assert receipt.controller_reported_version is None
    assert receipt.leader_ingress_event_id is None
    bundle = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file())
    assert encoded.encode("utf-8") not in bundle
    assert b"controller-secret" not in bundle


def test_encoded_unknown_field_fails_schema_without_persisting_remote_value(
    tmp_path: Path,
) -> None:
    encoded = base64.b64encode(b"controller-secret").decode("ascii")
    output = tmp_path / "unknown-encoded"
    with _server() as (server, root):
        server.version_extra = {"metadata": {"echo": encoded}}
        receipt = _transport(root).collect_runtime_evidence(output)

    assert receipt.status == "FAIL"
    bundle = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file())
    assert encoded.encode("utf-8") not in bundle
    assert b"controller-secret" not in bundle


@pytest.mark.parametrize("operation", ["probe", "submit"])
def test_transport_never_returns_a_receipt_when_self_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    real_verify = agentteams_transport.verify_hosted_agentteams_receipt

    def force_failure(receipt_path: Path) -> Any:
        validation = real_verify(receipt_path)
        return validation.model_copy(
            update={
                "status": "FAIL",
                "checks": {**validation.checks, "forced_failure": False},
                "reasons": ["forced_failure"],
            }
        )

    monkeypatch.setattr(
        agentteams_transport,
        "verify_hosted_agentteams_receipt",
        force_failure,
    )
    output = tmp_path / operation
    with _server() as (_server_instance, root):
        transport = _transport(
            root,
            mode=(
                AgentTeamsTransportMode.GATED
                if operation == "submit"
                else AgentTeamsTransportMode.SHADOW
            ),
            write_enabled=operation == "submit",
        )
        with pytest.raises(RuntimeError, match="failed offline validation"):
            if operation == "submit":
                transport.submit_project(
                    output,
                    _submission(),
                    approval_id="approval-forced-validation-failure",
                )
            else:
                transport.collect_runtime_evidence(output)

    validation_payload = json.loads(
        (output / "agentteams_hosted_validation.json").read_text(encoding="utf-8")
    )
    assert validation_payload["status"] == "FAIL"
    assert validation_payload["reasons"] == ["forced_failure"]


def test_write_requires_gated_mode_flag_and_named_approval(tmp_path: Path) -> None:
    request = HostedProjectSubmission(
        source_run_id="run-1",
        title="Audit",
        goal="Collect evidence",
    )
    with _server() as (_server_instance, root):
        with pytest.raises(PermissionError, match="mode=gated"):
            _transport(root).submit_project(
                tmp_path / "shadow",
                request,
                approval_id="approval-1",
            )
        with pytest.raises(PermissionError, match="disabled"):
            _transport(
                root,
                mode=AgentTeamsTransportMode.GATED,
                write_enabled=False,
            ).submit_project(
                tmp_path / "disabled",
                request,
                approval_id="approval-1",
            )


def test_hosted_receipt_detects_projection_tampering(tmp_path: Path) -> None:
    with _server() as (_server_instance, root):
        _transport(root).collect_runtime_evidence(tmp_path / "probe")
    team_path = tmp_path / "probe" / "agentteams_hosted_projection" / "team.json"
    team_path.write_bytes(team_path.read_bytes() + b" ")

    validation = verify_hosted_agentteams_receipt(
        tmp_path / "probe" / "agentteams_hosted_receipt.json"
    )

    assert validation.status == "FAIL"
    assert "projection_team_hash_matches" in validation.reasons


def test_unknown_projection_label_returns_structured_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "probe"
    with _server() as (_server_instance, root):
        _transport(root).collect_runtime_evidence(output)
    receipt_path = output / "agentteams_hosted_receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["evidence_projections"]["mystery"] = copy.deepcopy(
        payload["evidence_projections"]["team"]
    )
    _resign_receipt(receipt_path, payload)

    validation = verify_hosted_agentteams_receipt(receipt_path)

    assert validation.status == "FAIL"
    assert "projection_labels_known" in validation.reasons
    assert bridge_main(["validate-hosted-receipt", "--receipt", str(receipt_path)]) == 2
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["status"] == "FAIL"
    assert "projection_labels_known" in cli_payload["reasons"]


def test_malformed_projection_path_returns_structured_failure(tmp_path: Path) -> None:
    output = tmp_path / "probe"
    with _server() as (_server_instance, root):
        _transport(root).collect_runtime_evidence(output)
    receipt_path = output / "agentteams_hosted_receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["evidence_projections"]["team"]["path"] = "\x00invalid"
    _resign_receipt(receipt_path, payload)

    validation = verify_hosted_agentteams_receipt(receipt_path)

    assert validation.status == "FAIL"
    assert "projection_team_path_contained" in validation.reasons


def test_cli_malformed_hosted_receipt_is_structured_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_path = tmp_path / "malformed.json"
    receipt_path.write_bytes(b"not-json")

    assert bridge_main(["validate-hosted-receipt", "--receipt", str(receipt_path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["checks"] == {"receipt_schema_valid": False}
    assert payload["reasons"] == ["receipt_schema_valid"]


@pytest.mark.parametrize("tamper_kind", ["matrix_ingress", "workflow"])
def test_hosted_receipt_binds_sanitized_transport_endpoints(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    output = tmp_path / tamper_kind
    with _server() as (_server_instance, root):
        _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        ).submit_project(
            output,
            _submission(),
            approval_id="approval-exact-endpoint",
        )
    receipt_path = output / "agentteams_hosted_receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    if tamper_kind == "matrix_ingress":
        exchange = next(
            row for row in payload["transport_receipts"] if row["method"] == "PUT"
        )
        exchange["endpoint_id"] = "agentteams://team"
        expected_reason = "projection_matrix_ingress_bound_to_transport_receipt"
    else:
        workflow_sha = payload["evidence_projections"]["workflow"][
            "source_response_sha256"
        ]
        exchange = next(
            row
            for row in payload["transport_receipts"]
            if row["response_sha256"] == workflow_sha
        )
        exchange["endpoint_id"] = "agentteams://project"
        expected_reason = "projection_workflow_bound_to_transport_receipt"
    _resign_receipt(receipt_path, payload)

    validation = verify_hosted_agentteams_receipt(receipt_path)

    assert validation.status == "FAIL"
    assert expected_reason in validation.reasons


def test_hosted_receipt_requires_one_successful_matrix_put(tmp_path: Path) -> None:
    output = tmp_path / "duplicate-put"
    with _server() as (_server_instance, root):
        _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        ).submit_project(
            output,
            _submission(),
            approval_id="approval-unique-matrix-put",
        )
    receipt_path = output / "agentteams_hosted_receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    matrix_exchange = next(
        row for row in payload["transport_receipts"] if row["method"] == "PUT"
    )
    payload["transport_receipts"].append(copy.deepcopy(matrix_exchange))
    _resign_receipt(receipt_path, payload)

    validation = verify_hosted_agentteams_receipt(receipt_path)

    assert validation.status == "FAIL"
    assert "matrix_ingress_unique_successful_put" in validation.reasons


def test_hosted_receipt_binds_matrix_transaction_commitment(tmp_path: Path) -> None:
    output = tmp_path / "transaction-commitment"
    with _server() as (_server_instance, root):
        _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
        ).submit_project(
            output,
            _submission(),
            approval_id="approval-transaction-commitment",
        )
    receipt_path = output / "agentteams_hosted_receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["matrix_transaction_sha256"] = "0" * 64
    _resign_receipt(receipt_path, payload)

    validation = verify_hosted_agentteams_receipt(receipt_path)

    assert validation.status == "FAIL"
    assert "matrix_transaction_commitment_matches" in validation.reasons


def test_legacy_exact_wire_receipt_is_security_unverifiable(tmp_path: Path) -> None:
    receipt_path = tmp_path / "legacy.json"
    receipt_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "visiondata-gate.agentteams-hosted-receipt.v1",
                "receipt_sha256": "0" * 64,
            }
        )
    )

    validation = verify_hosted_agentteams_receipt(receipt_path)

    assert validation.status == "FAIL"
    assert validation.reasons == ["legacy_exact_wire_security_unverifiable"]


def test_probe_fails_closed_when_expected_skill_is_missing(tmp_path: Path) -> None:
    with _server() as (server, root):
        server.worker_payload["workers"][0]["skills"] = []
        receipt = _transport(root).collect_runtime_evidence(tmp_path / "probe")

    assert receipt.status == "FAIL"
    assert receipt.skill_specs_verified is False
    assert receipt.operation_status == "CONTROLLER_CONNECTED"
    assert (
        verify_hosted_agentteams_receipt(
            tmp_path / "probe" / "agentteams_hosted_receipt.json"
        ).status
        == "PASS"
    )


def test_controller_project_post_is_never_automatically_retried(
    tmp_path: Path,
) -> None:
    request = HostedProjectSubmission(
        source_run_id="run-no-retry",
        title="No retry",
        goal="Verify the write retry boundary.",
    )
    with _server() as (server, root):
        server.project_fail_status = 503
        transport = _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
            read_max_retries=2,
        )
        with pytest.raises(RuntimeError, match="HTTP status failure"):
            transport.submit_project(
                tmp_path / "submit",
                request,
                approval_id="approval-no-retry",
            )

    assert server.counts["POST /api/v1/projects"] == 1


def test_matrix_put_uses_bounded_retry_with_same_transaction_id(
    tmp_path: Path,
) -> None:
    request = HostedProjectSubmission(
        source_run_id="run-matrix-retry",
        title="Matrix retry",
        goal="Verify stable Matrix transaction retry.",
    )
    with _server() as (server, root):
        server.matrix_fail_once = True
        transport = _transport(
            root,
            mode=AgentTeamsTransportMode.GATED,
            write_enabled=True,
            read_max_retries=1,
        )
        receipt = transport.submit_project(
            tmp_path / "submit",
            request,
            approval_id="approval-matrix-retry",
        )

    assert receipt.status == "PASS"
    assert len(server.matrix_attempts) == 1
    assert next(iter(server.matrix_attempts.values())) == 2
    assert len(server.matrix_events) == 1
    assert any(
        exchange.method == "PUT" and exchange.status == "RECOVERED"
        for exchange in receipt.transport_receipts
    )
