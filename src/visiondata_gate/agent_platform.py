"""Read-only, scoped platform inventory. No model probes or task execution."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from .evidence import canonical_json_bytes
from .product_models import ProductModel, TaskExecutionStatus
from .provider_profiles import ProviderProfileStatus
from .task_store import NotFoundError
from .tools import tool_catalog

if TYPE_CHECKING:
    from .product_service import ProductService


class PlatformScope(ProductModel):
    mode: Literal["LOCAL_WORKSPACE"] = "LOCAL_WORKSPACE"
    production_authentication: Literal[False] = False


class PlatformCapability(ProductModel):
    capability_id: str
    name: str
    kind: Literal["TOOL", "RUNTIME", "PLANNER"]
    status: Literal["REGISTERED_LOCAL", "REQUIRES_CONFIGURATION"]
    description: str


class PlatformProviders(ProductModel):
    configured_count: int = Field(ge=0)
    enabled_count: int = Field(ge=0)
    connection_status: Literal["NOT_PROBED"] = "NOT_PROBED"


class PlatformTask(ProductModel):
    task_id: str
    goal: str
    execution_status: TaskExecutionStatus
    final_decision: str | None
    updated_at: str


class AgentPlatformReport(ProductModel):
    schema_version: Literal["visiondata-gate.agent-platform.v1"] = (
        "visiondata-gate.agent-platform.v1"
    )
    workspace_id: str
    project_id: str | None
    scope: PlatformScope = Field(default_factory=PlatformScope)
    capabilities: list[PlatformCapability]
    providers: PlatformProviders
    tasks: list[PlatformTask]
    task_count: int = Field(ge=0)
    task_limit: Literal[200] = 200
    tasks_truncated: bool
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_agent_platform(
    service: ProductService,
    actor: str,
    workspace_id: str,
    project_id: str | None = None,
) -> AgentPlatformReport:
    if project_id is not None:
        project = service.get_project(actor, project_id)
        if project.workspace_id != workspace_id:
            raise NotFoundError("project not found in workspace")
    # One SELECT yields a consistent total and bounded task slice.
    with service.store._connection() as connection:
        service.store._require_membership(connection, workspace_id, actor)
        params = [workspace_id]
        clause = "workspace_id = ?"
        if project_id is not None:
            clause += " AND project_id = ?"
            params.append(project_id)
        rows = connection.execute(
            "SELECT task_id, goal, execution_status, final_decision, updated_at, "
            f"COUNT(*) OVER() AS matching_count FROM agent_tasks WHERE {clause} "
            "ORDER BY created_at DESC, task_id DESC LIMIT 200",
            params,
        ).fetchall()
    profiles = service.list_provider_profiles(actor, workspace_id)
    names = {
        "image_quality": "图像质量",
        "duplicate_leakage": "重复与泄漏",
        "annotation_integrity": "标注完整性",
        "coverage_matrix": "覆盖矩阵",
        "governance_audit": "治理合同核验",
    }
    capabilities = [
        PlatformCapability(
            capability_id=str(item["name"]),
            name=names[str(item["name"])],
            kind="TOOL",
            status="REGISTERED_LOCAL",
            description=f"本地白名单工具；权限 {item['permission']}；仅在任务中实际执行时生成测量回执。",
        )
        for item in tool_catalog(include_optional=True)
    ]
    capabilities.extend(
        [
            PlatformCapability(
                capability_id="execution_recovery",
                name="显式中断恢复",
                kind="RUNTIME",
                status="REGISTERED_LOCAL",
                description="仅恢复有执行归属记录且已无执行者的任务；新任务需要重新批准。",
            ),
            PlatformCapability(
                capability_id="model_usage",
                name="模型调用核算",
                kind="RUNTIME",
                status="REGISTERED_LOCAL",
                description="从已核验回执读取用量；缺报数据与未知费用不按零计算。",
            ),
            PlatformCapability(
                capability_id="model_planner",
                name="可替换模型 Planner",
                kind="PLANNER",
                status="REQUIRES_CONFIGURATION",
                description="支持受控模型建议；配置存在不等于供应商已连接或本任务已调用。",
            ),
        ]
    )
    tasks = [
        PlatformTask(**{key: row[key] for key in PlatformTask.model_fields})
        for row in rows
    ]
    task_count = rows[0]["matching_count"] if rows else 0
    stable = {
        "schema_version": "visiondata-gate.agent-platform.v1",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "scope": PlatformScope(),
        "capabilities": capabilities,
        "providers": PlatformProviders(
            configured_count=len(profiles),
            enabled_count=sum(
                p.status is ProviderProfileStatus.ACTIVE for p in profiles
            ),
        ),
        "tasks": tasks,
        "task_count": task_count,
        "task_limit": 200,
        "tasks_truncated": task_count > len(tasks),
    }
    return AgentPlatformReport(
        **stable,
        receipt_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )
