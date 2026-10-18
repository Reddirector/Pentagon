"""Workflows API: create, list, inspect, edit, execute, and monitor workflows.

Every operation is strictly scoped by user_id to enforce user isolation.
Built-in executive templates are returned alongside user custom workflows.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Workflow, WorkflowRun
from app.db.session import get_db
from app.security.keys import resolve_api_key
from app.services.workflow_engine import (
    EXECUTIVE_TEMPLATES,
    execute_workflow_run,
    get_template_by_id,
    validate_and_sort_dag,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    icon: str = Field(default="workflow", max_length=64)
    category: str = Field(default="general", max_length=64)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    icon: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class WorkflowRunRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    inputs: dict[str, Any] = Field(default_factory=dict)


def _serialize_workflow(wf: Workflow) -> dict[str, Any]:
    return {
        "id": wf.id,
        "user_id": wf.user_id,
        "name": wf.name,
        "description": wf.description,
        "icon": wf.icon,
        "category": wf.category,
        "is_template": wf.is_template,
        "nodes": wf.nodes or [],
        "edges": wf.edges or [],
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
        "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
    }


def _serialize_run(run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "user_id": run.user_id,
        "status": run.status,
        "inputs": run.inputs or {},
        "step_results": run.step_results or {},
        "outputs": run.outputs or {},
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("")
async def list_workflows(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all workflows for this user, including pre-built executive templates."""
    user_wfs = db.scalars(
        select(Workflow)
        .where(Workflow.user_id == user_id)
        .order_by(Workflow.updated_at.desc())
    ).all()

    serialized_user = [_serialize_workflow(w) for w in user_wfs]
    return {
        "templates": EXECUTIVE_TEMPLATES,
        "workflows": serialized_user,
    }


@router.post("")
async def create_workflow(
    payload: WorkflowCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new custom workflow."""
    # Ensure user row exists
    user = db.scalar(select(User).where(User.id == payload.user_id))
    if user is None:
        user = User(id=payload.user_id)
        db.add(user)
        db.commit()

    # Validate graph structure
    try:
        validate_and_sort_dag(payload.nodes, payload.edges)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    wf = Workflow(
        user_id=payload.user_id,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        category=payload.category,
        is_template=False,
        nodes=payload.nodes,
        edges=payload.edges,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return _serialize_workflow(wf)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a workflow definition (template or user-owned)."""
    # Check templates
    template = get_template_by_id(workflow_id)
    if template:
        return template

    wf = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return _serialize_workflow(wf)


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a user-owned workflow definition."""
    wf = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == payload.user_id)
    )
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found or owned by user.")

    if payload.nodes is not None or payload.edges is not None:
        new_nodes = payload.nodes if payload.nodes is not None else wf.nodes
        new_edges = payload.edges if payload.edges is not None else wf.edges
        try:
            validate_and_sort_dag(new_nodes, new_edges)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        wf.nodes = new_nodes
        wf.edges = new_edges

    if payload.name is not None:
        wf.name = payload.name
    if payload.description is not None:
        wf.description = payload.description
    if payload.icon is not None:
        wf.icon = payload.icon
    if payload.category is not None:
        wf.category = payload.category

    db.commit()
    db.refresh(wf)
    return _serialize_workflow(wf)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a user-owned workflow and all associated runs."""
    wf = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found or owned by user.")

    db.delete(wf)
    db.commit()
    return {"status": "deleted", "workflow_id": workflow_id}


@router.post("/{workflow_id}/run")
async def trigger_workflow_run(
    workflow_id: str,
    payload: WorkflowRunRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger an asynchronous execution run of a workflow."""
    # Ensure user exists
    user = db.scalar(select(User).where(User.id == payload.user_id))
    if user is None:
        user = User(id=payload.user_id)
        db.add(user)
        db.commit()

    # Verify API key is available
    try:
        api_key = resolve_api_key(db, payload.user_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="NVIDIA API Key is required to run workflows. Please set your key in Settings."
        )

    # Check workflow exists (either user-owned or template)
    template = get_template_by_id(workflow_id)
    if template:
        # Fork/instantiate template for user if not yet instantiated, or run template directly
        wf_id = workflow_id
        # If template, create a user workflow instance so it can be tracked and saved
        existing_copy = db.scalar(
            select(Workflow).where(Workflow.user_id == payload.user_id, Workflow.name == template["name"])
        )
        if existing_copy is None:
            user_wf = Workflow(
                user_id=payload.user_id,
                name=template["name"],
                description=template["description"],
                icon=template["icon"],
                category=template["category"],
                is_template=False,
                nodes=template["nodes"],
                edges=template["edges"],
            )
            db.add(user_wf)
            db.commit()
            db.refresh(user_wf)
            wf_id = user_wf.id
        else:
            wf_id = existing_copy.id
    else:
        wf = db.scalar(
            select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == payload.user_id)
        )
        if wf is None:
            raise HTTPException(status_code=404, detail="Workflow not found.")
        wf_id = wf.id

    run = WorkflowRun(
        workflow_id=wf_id,
        user_id=payload.user_id,
        status="pending",
        inputs=payload.inputs,
        step_results={},
        outputs={"files": []},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Launch execution as an asynchronous background task
    asyncio.create_task(execute_workflow_run(run.id, payload.user_id, api_key))

    return _serialize_run(run)


@router.get("/runs/{run_id}")
async def get_workflow_run(
    run_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get real-time execution state, step results, logs, and generated files for a run."""
    run = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.user_id == user_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found.")
    return _serialize_run(run)


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List execution history for a workflow."""
    runs = db.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id, WorkflowRun.user_id == user_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(20)
    ).all()
    return {"runs": [_serialize_run(r) for r in runs]}
