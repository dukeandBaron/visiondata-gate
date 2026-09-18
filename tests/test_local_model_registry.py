from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError


def registry_module():
    assert importlib.util.find_spec("visiondata_gate.local_model_registry"), (
        "Local visual model registry is not implemented"
    )
    return importlib.import_module("visiondata_gate.local_model_registry")


@pytest.fixture
def product_scope(tmp_path):
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    user = product.create_user(CreateUserRequest(display_name="Model reviewer"))
    workspace = product.create_workspace(
        CreateWorkspaceRequest(name="Vision", owner_user_id=user.user_id)
    )
    project = product.create_project(
        user.user_id,
        CreateProjectRequest(workspace_id=workspace.workspace_id, name="Models"),
    )
    yield product, user.user_id, project.project_id
    product.close(wait=True)


def model_request(module, path: Path, **updates):
    return module.RegisterVisionModel(
        **{
            "request_key": "model-register-0001",
            "reviewer_identity": "Named quality reviewer",
            "note": "Register local synthetic bytes, never deserialize",
            "display_name": "Unloaded detection artifact",
            "weights_path": str(path),
            "expected_weights_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "task_type": "detect",
            "license_id": "AGPL-3.0",
            "source_description": "Synthetic test fixture",
            "operator_attests_read_authorized": True,
            **updates,
        }
    )


def test_registers_bytes_without_loading_and_is_idempotent(product_scope, tmp_path):
    module = registry_module()
    product, actor, project_id = product_scope
    path = tmp_path / "untrusted.pt"
    path.write_bytes(b"not a torch checkpoint; registration must not deserialize")
    service = module.LocalVisionModelService(product)
    request = model_request(module, path)
    first = service.register_model(actor, project_id, request)
    assert first == service.register_model(actor, project_id, request)
    assert first["status"] == "REGISTERED_NOT_LOADED"
    assert first["loaded"] is False
    assert first["production_release_allowed"] is False
    assert first["weights_sha256"] == request.expected_weights_sha256
    assert str(path) not in json.dumps(first)
    assert service.get_model(actor, project_id, first["model_id"]) == first
    assert service.list_models(actor, project_id)["items"] == [first]
    assert (
        service.get_operation(actor, project_id, "register_model", request.request_key)[
            "resource_id"
        ]
        == first["model_id"]
    )


def test_model_registration_rejects_drift_and_scope(product_scope, tmp_path):
    module = registry_module()
    product, actor, project_id = product_scope
    path = tmp_path / "checkpoint.pt"
    path.write_bytes(b"unloaded")
    service = module.LocalVisionModelService(product)
    request = model_request(module, path)
    with pytest.raises(NotFoundError):
        service.register_model("outsider", project_id, request)
    wrong = request.model_copy(update={"expected_weights_sha256": "0" * 64})
    with pytest.raises(module.VisionModelError, match="WEIGHTS_CHANGED"):
        service.register_model(actor, project_id, wrong)
    first = service.register_model(actor, project_id, request)
    changed = request.model_copy(update={"display_name": "changed request"})
    with pytest.raises(module.VisionModelError, match="IDEMPOTENCY_CONFLICT"):
        service.register_model(actor, project_id, changed)
    with pytest.raises(NotFoundError):
        service.get_model("outsider", project_id, first["model_id"])


def test_capabilities_keep_visual_and_llm_adaptation_boundaries(product_scope):
    module = registry_module()
    product, actor, project_id = product_scope
    result = module.LocalVisionModelService(product).capabilities(actor, project_id)
    assert result["model_domain"] == "LOCAL_VISUAL_MODELS"
    assert result["llm_provider_managed"] is False
    assert result["supported_registration_tasks"] == ["detect", "segment", "normality"]
    assert result["executable_inference_tasks"] == ["normality"]
    assert result["normality_runtime"] == "EXTERNAL_RUNTIME_REQUIRED"
    assert result["ttt_status"] == "NORMALITY_EPISODIC_AVAILABLE"
    assert result["ttt_scope"] == "NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE"
    assert module.CreateVisionTrainingRun.model_fields["adaptation"].default == "OFF"
    assert result["weight_download_allowed"] is False
    assert result["registered_model_count"] == 0
    assert result["registered_runtime_count"] == 0
    assert result["sandbox_approved_normality_model_count"] == 0
    assert result["registered_inference_asset_count"] == 0
    assert result["completed_normality_inference_count"] == 0
    assert result["training_ready"] is False
    assert result["production_release_allowed"] is False


@pytest.mark.parametrize("value", [1, "true", None])
def test_unbound_fixture_seam_requires_literal_boolean(product_scope, value):
    module = registry_module()
    product, _actor, _project_id = product_scope

    with pytest.raises(TypeError, match="_test_only_allow_unbound_fixtures"):
        module.LocalVisionModelService(product, _test_only_allow_unbound_fixtures=value)


@pytest.mark.parametrize("grant", [1, "true", "1"])
def test_named_authority_requires_json_boolean(tmp_path, grant):
    from pydantic import ValidationError

    module = registry_module()
    path = tmp_path / "artifact.pt"
    path.write_bytes(b"unloaded")
    with pytest.raises(ValidationError):
        model_request(module, path, operator_attests_read_authorized=grant)
