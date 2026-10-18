"""Pentagon Workflow Orchestration Engine.

Manages directed acyclic graph (DAG) workflow definitions, topological step
sequencing, real-time node execution with live progress logging, variable templating,
and multi-modal artifact generation (documents, images, research synthesis).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.models import Conversation, GeneratedFile, Workflow, WorkflowRun, utc_now
from app.services.document_builder import CONTENT_TYPES, EXTENSIONS, build_document, safe_filename
from app.services.file_storage import build_key, get_storage
from app.services.image_generator import generate_image
from app.services.nvidia_client import make_chat_model
from app.services.web_search import search_web

logger = logging.getLogger(__name__)

# Variable interpolation regex: matches {{inputs.topic}} or {{steps.node_id.output}}
_VAR_REGEX = re.compile(r"\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}")


def get_nested_val(data: dict[str, Any], path: str) -> Any:
    """Traverse a dot-separated path in nested dictionaries."""
    parts = path.split(".")
    curr: Any = data
    for part in parts:
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        elif isinstance(curr, (list, tuple)) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(curr):
                curr = curr[idx]
            else:
                return None
        else:
            return None
    return curr


def render_template(val: Any, context: dict[str, Any]) -> Any:
    """Recursively resolve {{variable}} expressions in strings, dicts, and lists."""
    if isinstance(val, str):
        # If the string is purely a single variable expression, return the raw value
        match = _VAR_REGEX.fullmatch(val.strip())
        if match:
            resolved = get_nested_val(context, match.group(1))
            return resolved if resolved is not None else ""

        def replace_var(m: re.Match[str]) -> str:
            resolved = get_nested_val(context, m.group(1))
            if resolved is None:
                return ""
            if isinstance(resolved, (dict, list)):
                import json
                return json.dumps(resolved, ensure_ascii=False)
            return str(resolved)

        return _VAR_REGEX.sub(replace_var, val)

    elif isinstance(val, dict):
        return {k: render_template(v, context) for k, v in val.items()}
    elif isinstance(val, list):
        return [render_template(item, context) for item in val]
    return val


def validate_and_sort_dag(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate graph structure and return nodes in topological execution order."""
    node_map = {n["id"]: n for n in nodes if "id" in n}
    if not node_map:
        return []

    in_degree = {nid: 0 for nid in node_map}
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_map}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in node_map and tgt in node_map:
            adjacency[src].append(tgt)
            in_degree[tgt] += 1

    # Kahn's algorithm for topological sorting
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    sorted_nodes: list[dict[str, Any]] = []

    while queue:
        curr_id = queue.pop(0)
        sorted_nodes.append(node_map[curr_id])
        for neighbor in adjacency[curr_id]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_nodes) != len(node_map):
        raise ValueError("Workflow graph contains a dependency cycle or unreachable circular loops.")

    return sorted_nodes


# ==============================================================================
# Built-in Executive Templates
# ==============================================================================

EXECUTIVE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "tpl-deep-market-research",
        "name": "Deep Market Research & Executive Whitepaper",
        "description": "Autonomous multi-step pipeline: conducts deep web intelligence, synthesizes strategic SWOT and market data, generates a high-resolution conceptual graphic, and compiles an executive whitepaper (PDF/DOCX) with embedded visuals.",
        "icon": "book-open",
        "category": "research",
        "is_template": True,
        "nodes": [
            {
                "id": "step_1_trigger",
                "type": "trigger",
                "title": "Research Parameters",
                "description": "Configures market sector, research queries, and target audience.",
                "config": {
                    "topic": "Autonomous AI Agents in Enterprise 2026",
                    "target_audience": "C-Suite & Technology Leaders",
                    "depth": "comprehensive",
                },
                "position": {"x": 80, "y": 100},
            },
            {
                "id": "step_2_web_search",
                "type": "web_search",
                "title": "Deep Web Intelligence",
                "description": "Gathers live market size, competitive dynamics, and regulatory developments.",
                "config": {
                    "query": "{{inputs.topic}} market size trends landscape competitors 2025 2026",
                    "max_sources": 5,
                },
                "position": {"x": 340, "y": 100},
            },
            {
                "id": "step_3_llm_analysis",
                "type": "llm_transform",
                "title": "Strategic Industry Synthesis",
                "description": "Synthesizes competitive SWOT, data analysis, and strategic recommendations.",
                "config": {
                    "model": "meta/llama-3.2-11b-vision-instruct",
                    "prompt": (
                        "You are an elite corporate strategy consultant and market analyst. Analyze the following market intelligence regarding {{inputs.topic}} for {{inputs.target_audience}}.\n\n"
                        "Live Intelligence:\n{{steps.step_2_web_search.output}}\n\n"
                        "Produce a comprehensive, rigorous executive whitepaper structured in clean GitHub-style Markdown with:\n"
                        "# {{inputs.topic}}: Executive Strategic Whitepaper\n"
                        "> [!IMPORTANT] Executive Thesis and Macro Market Takeaways\n\n"
                        "## 1. Market Opportunity & Industry Landscape\n"
                        "## 2. Competitive Matrix & Strategic Positioning\n"
                        "Include a structured markdown comparison table with columns: Competitor / Tier, Core Capabilities, Strategic Moat, Market Share Vulnerability.\n\n"
                        "## 3. Technology Architecture & Implementation Vectors\n"
                        "## 4. Comprehensive SWOT Analysis\n"
                        "Use clear bullet points covering Strengths, Weaknesses, Opportunities, and Threats.\n\n"
                        "> [!TIP] Strategic Recommendations for {{inputs.target_audience}}\n"
                        "## 5. Strategic Roadmap & Financial Implications\n"
                        "Provide concrete timeline phases and ROI projections."
                    ),
                },
                "position": {"x": 600, "y": 100},
            },
            {
                "id": "step_4_image_gen",
                "type": "image_generation",
                "title": "Executive Architecture Visual",
                "description": "Generates a clean, photorealistic architectural illustration.",
                "config": {
                    "title": "Executive Architecture Visual",
                    "prompt": "{{inputs.topic}} clean modern technical architecture diagram, corporate infographic style, high-tech enterprise AI workflow, sharp vector graphics, minimalist, clear visual hierarchy",
                    "style": "diagram",
                    "aspect_ratio": "16:9",
                },
                "position": {"x": 860, "y": 100},
            },
            {
                "id": "step_5_doc_export",
                "type": "document_generation",
                "title": "Compile Executive Whitepaper",
                "description": "Compiles the final deliverable into a professionally formatted PDF or DOCX file with embedded visuals.",
                "config": {
                    "format": "pdf",
                    "title": "{{inputs.topic}} - Executive Whitepaper",
                    "content": (
                        "{{steps.step_3_llm_analysis.output}}\n\n"
                        "---\n\n"
                        "## Conceptual System Architecture\n\n"
                        "![Architecture Visual](/api/files/{{steps.step_4_image_gen.output.file_id}}/download?inline=true)\n\n"
                        "*Figure 1: High-level architectural topology generated by Pentagon Workflow Engine.*"
                    ),
                },
                "position": {"x": 1120, "y": 100},
            },
        ],
        "edges": [
            {"id": "e1-2", "source": "step_1_trigger", "target": "step_2_web_search"},
            {"id": "e2-3", "source": "step_2_web_search", "target": "step_3_llm_analysis"},
            {"id": "e3-4", "source": "step_3_llm_analysis", "target": "step_4_image_gen"},
            {"id": "e4-5", "source": "step_4_image_gen", "target": "step_5_doc_export"},
        ],
    },
    {
        "id": "tpl-pitch-deck-financials",
        "name": "Startup Pitch Deck & Financial Model",
        "description": "Generates a complete investment pitch package: an investor-ready 10-slide PowerPoint presentation (.pptx) and a formatted 3-year multi-sheet Excel financial workbook (.xlsx).",
        "icon": "presentation",
        "category": "finance",
        "is_template": True,
        "nodes": [
            {
                "id": "node_trigger",
                "type": "trigger",
                "title": "Venture Parameters",
                "description": "Startup details, round target, and valuation metrics.",
                "config": {
                    "startup_name": "AetherPulse AI",
                    "tagline": "Autonomous Cloud Reliability & Self-Healing Infrastructure",
                    "raise_amount": "$12M Series A",
                    "target_market": "Global Enterprise DevOps & Cloud Platforms",
                },
                "position": {"x": 80, "y": 100},
            },
            {
                "id": "node_deck_content",
                "type": "llm_transform",
                "title": "Deck Narrative Architect",
                "description": "Structures 10 punchy, high-impact investor slides.",
                "config": {
                    "model": "meta/llama-3.2-11b-vision-instruct",
                    "prompt": (
                        "You are a top Silicon Valley venture partner helping {{inputs.startup_name}} prepare their {{inputs.raise_amount}} investor pitch deck.\n"
                        "Startup Tagline: {{inputs.tagline}}\n"
                        "Market: {{inputs.target_market}}\n\n"
                        "Create a complete 10-slide presentation deck. Return in markdown where each slide begins with '# Slide [Number]: [Title]' followed by high-conviction bullet points and metrics.\n"
                        "Slides must cover:\n"
                        "1. Vision & Hook\n"
                        "2. The Critical Enterprise Problem\n"
                        "3. The {{inputs.startup_name}} Breakthrough Solution\n"
                        "4. TAM, SAM & SOM Market Dynamics\n"
                        "5. Proprietary Technology Moat & Architecture\n"
                        "6. Traction & Customer Proof Points\n"
                        "7. Business Model & Unit Economics\n"
                        "8. Competitive Landscape & Defensibility\n"
                        "9. Financial Projections & Milestones\n"
                        "10. The Ask: {{inputs.raise_amount}} Use of Capital"
                    ),
                },
                "position": {"x": 360, "y": 100},
            },
            {
                "id": "node_deck_pptx",
                "type": "document_generation",
                "title": "Compile PowerPoint Deck (.pptx)",
                "description": "Exports a formatted PowerPoint presentation deck file.",
                "config": {
                    "format": "pptx",
                    "title": "{{inputs.startup_name}} - Series A Pitch Deck",
                    "content": "{{steps.node_deck_content.output}}",
                },
                "position": {"x": 640, "y": 60},
            },
            {
                "id": "node_financial_excel",
                "type": "document_generation",
                "title": "Compile Financial Model (.xlsx)",
                "description": "Exports a formatted 3-year P&L spreadsheet workbook.",
                "config": {
                    "format": "xlsx",
                    "title": "{{inputs.startup_name}} - 3-Year Financial Model",
                    "content": {
                        "sheets": [
                            {
                                "name": "Income Statement",
                                "columns": ["Metric", "Year 1 ($k)", "Year 2 ($k)", "Year 3 ($k)", "YoY Growth"],
                                "rows": [
                                    ["ARR (Ending)", 1800, 5400, 14200, "163%"],
                                    ["Cost of Goods Sold (Cloud)", 320, 850, 1950, "129%"],
                                    ["Gross Profit", 1480, 4550, 12250, "169%"],
                                    ["Gross Margin %", "82.2%", "84.3%", "86.3%", "+200 bps"],
                                    ["R&D Expenses", 2200, 4100, 7200, "76%"],
                                    ["Sales & Marketing", 1400, 3200, 6100, "91%"],
                                    ["G&A Expenses", 450, 850, 1400, "65%"],
                                    ["EBITDA", -2570, -3600, -2450, "Approaching Breakeven"],
                                    ["Ending Cash Balance", 10430, 6830, 4380, "Runway > 24 mo"],
                                ]
                            },
                            {
                                "name": "Unit Economics",
                                "columns": ["KPI", "Current", "Target Y2", "Target Y3"],
                                "rows": [
                                    ["CAC Payback (Months)", 11, 8, 6],
                                    ["Net Revenue Retention (NRR)", "128%", "135%", "142%"],
                                    ["Magic Number", "1.3x", "1.5x", "1.7x"],
                                    ["Enterprise ACV ($k)", 75, 120, 160],
                                    ["Gross Revenue Retention (GRR)", "96%", "97%", "98%"],
                                ]
                            }
                        ]
                    },
                },
                "position": {"x": 640, "y": 200},
            },
        ],
        "edges": [
            {"id": "ep1-2", "source": "node_trigger", "target": "node_deck_content"},
            {"id": "ep2-3", "source": "node_deck_content", "target": "node_deck_pptx"},
            {"id": "ep2-4", "source": "node_deck_content", "target": "node_financial_excel"},
        ],
    },
    {
        "id": "tpl-content-visual-suite",
        "name": "Multi-Channel Content & Visual Asset Suite",
        "description": "Generates a cohesive product announcement pack: technical blog post, executive LinkedIn essay, viral Twitter/X thread, photorealistic hero banner, and downloadable styled HTML press package.",
        "icon": "sparkles",
        "category": "marketing",
        "is_template": True,
        "nodes": [
            {
                "id": "cms_trigger",
                "type": "trigger",
                "title": "Campaign Launch Brief",
                "description": "Defines core value proposition, product name, and launch targets.",
                "config": {
                    "product_name": "Pentagon Autonomous Workflow Studio",
                    "core_message": "Build, orchestrate, and execute complex multi-modal agent workflows with live visual DAG pipelines.",
                    "target_platform": "DevOps & Engineering Leaders",
                },
                "position": {"x": 80, "y": 100},
            },
            {
                "id": "cms_image_gen",
                "type": "image_generation",
                "title": "Hero Visual Banner",
                "description": "Generates a stunning photorealistic 16:9 hero image.",
                "config": {
                    "title": "{{inputs.product_name}} - Hero Banner",
                    "prompt": "{{inputs.product_name}} cinematic still, futuristic glowing node workflow graph floating in high-tech control room, 35mm photography, volumetric lighting, 8k resolution",
                    "style": "cinematic",
                    "aspect_ratio": "16:9",
                },
                "position": {"x": 360, "y": 100},
            },
            {
                "id": "cms_copy_gen",
                "type": "llm_transform",
                "title": "Omni-Channel Content Drafter",
                "description": "Synthesizes blog post, LinkedIn executive article, and Twitter/X thread.",
                "config": {
                    "model": "meta/llama-3.2-11b-vision-instruct",
                    "prompt": (
                        "You are an elite product marketing leader. Draft a multi-channel launch kit for:\n"
                        "Product: {{inputs.product_name}}\n"
                        "Core Message: {{inputs.core_message}}\n"
                        "Target Audience: {{inputs.target_platform}}\n\n"
                        "Draft the following 3 distinct assets in formatted markdown:\n"
                        "## 1. Technical Launch Blog Post (1,000 words, architectural depth, code snippets)\n"
                        "## 2. Thought-Leadership LinkedIn Post (Hook, problem statement, key insights, call to action)\n"
                        "## 3. Viral 7-Tweet Announcement Thread (Numbered 1/7 to 7/7, punchy, emoji accents)"
                    ),
                },
                "position": {"x": 640, "y": 100},
            },
            {
                "id": "cms_press_doc",
                "type": "document_generation",
                "title": "Compile Interactive Launch Kit (.html)",
                "description": "Produces a styled, downloadable HTML media document with embedded hero graphic.",
                "config": {
                    "format": "html",
                    "title": "{{inputs.product_name}} - Official Launch Kit",
                    "content": (
                        "# {{inputs.product_name}}\n\n"
                        "![Hero Banner](/api/files/{{steps.cms_image_gen.output.file_id}}/download?inline=true)\n\n"
                        "{{steps.cms_copy_gen.output}}"
                    ),
                },
                "position": {"x": 920, "y": 100},
            },
        ],
        "edges": [
            {"id": "ec1-2", "source": "cms_trigger", "target": "cms_image_gen"},
            {"id": "ec2-3", "source": "cms_image_gen", "target": "cms_copy_gen"},
            {"id": "ec3-4", "source": "cms_copy_gen", "target": "cms_press_doc"},
        ],
    },
]


def get_template_by_id(template_id: str) -> dict[str, Any] | None:
    for tpl in EXECUTIVE_TEMPLATES:
        if tpl["id"] == template_id:
            return dict(tpl)
    return None


# ==============================================================================
# Step Execution Handlers
# ==============================================================================

async def _ensure_workflow_conversation(user_id: str, workflow_name: str, db: Session) -> Conversation:
    """Find or create a designated conversation for workflow run artifacts."""
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.title == f"Workflow: {workflow_name}")
        .order_by(Conversation.updated_at.desc())
    )
    if conv is None:
        conv = Conversation(
            user_id=user_id,
            title=f"Workflow: {workflow_name[:80]}",
            active_model="meta/llama-3.2-11b-vision-instruct",
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


async def execute_node(
    node: dict[str, Any],
    context: dict[str, Any],
    user_id: str,
    api_key: str,
    conversation_id: str,
    db: Session,
) -> dict[str, Any]:
    """Execute a single workflow node and return its output payload and logs."""
    node_type = node.get("type")
    config = node.get("config", {})
    logs: list[str] = []

    logs.append(f"Starting execution for node '{node.get('title', node.get('id'))}' (type: {node_type})")

    if node_type == "trigger":
        # Pass through the trigger inputs
        rendered_config = render_template(config, context)
        logs.append(f"Received trigger configuration with {len(rendered_config)} input fields.")
        return {"output": rendered_config, "logs": logs}

    elif node_type == "web_search":
        raw_query = config.get("query", "")
        rendered_query = str(render_template(raw_query, context)).strip()
        max_sources = int(config.get("max_sources", 4))
        logs.append(f"Executing web intelligence search: '{rendered_query}'")

        try:
            results = await search_web(rendered_query)
            trimmed = results[:max_sources]
            logs.append(f"Successfully retrieved {len(trimmed)} grounded intelligence sources.")
            
            # Format text summary for downstream LLMs
            formatted_text = "\n\n".join(
                f"### Source: {r.get('title')} ({r.get('url')})\n{r.get('content')[:1200]}"
                for r in trimmed
            )
            return {
                "output": formatted_text,
                "sources": trimmed,
                "query": rendered_query,
                "logs": logs,
            }
        except Exception as exc:
            logger.warning("Web search error in workflow: %s", exc)
            fallback_msg = f"Web search could not retrieve external sources ({exc}). Proceeding with internal foundation knowledge."
            logs.append(f"Search warning: {fallback_msg}")
            return {"output": fallback_msg, "sources": [], "logs": logs}

    elif node_type == "llm_transform":
        raw_prompt = config.get("prompt", "")
        model_name = config.get("model") or "meta/llama-3.2-11b-vision-instruct"
        rendered_prompt = str(render_template(raw_prompt, context))
        logs.append(f"Invoking LLM transform ({model_name}) with {len(rendered_prompt)} character prompt.")

        chat_model = make_chat_model(api_key=api_key, model=model_name)
        from langchain_core.messages import HumanMessage

        response = await chat_model.ainvoke([HumanMessage(content=rendered_prompt)])
        content = response.content if hasattr(response, "content") else str(response)
        content_str = str(content).strip()
        logs.append(f"LLM generated {len(content_str)} characters of output.")
        return {"output": content_str, "model": model_name, "logs": logs}

    elif node_type == "image_generation":
        raw_prompt = config.get("prompt", "")
        raw_title = config.get("title", "Workflow Visual Graphic")
        style = config.get("style", "photorealistic")
        aspect_ratio = config.get("aspect_ratio", "16:9")

        rendered_prompt = str(render_template(raw_prompt, context))
        rendered_title = str(render_template(raw_title, context))
        logs.append(f"Generating {style} image with prompt: '{rendered_prompt[:90]}...'")

        image_bytes, mime_type = await generate_image(
            prompt=rendered_prompt,
            style=style,
            aspect_ratio=aspect_ratio,
        )

        filename = safe_filename(rendered_title, "jpg")
        file_id = str(uuid4())
        storage_path = build_key(user_id, conversation_id, file_id, ".jpg")
        storage = get_storage()
        await storage.put(storage_path, image_bytes, mime_type)

        record = GeneratedFile(
            id=file_id,
            user_id=user_id,
            conversation_id=conversation_id,
            filename=filename,
            format="jpg",
            media_type=mime_type,
            size_bytes=len(image_bytes),
            storage_path=storage_path,
        )
        db.add(record)
        db.commit()

        download_url = f"/api/files/{file_id}/download"
        logs.append(f"Image successfully rendered and stored: {filename} ({len(image_bytes)} bytes)")
        return {
            "output": {
                "file_id": file_id,
                "filename": filename,
                "format": "jpg",
                "size_bytes": len(image_bytes),
                "download_url": download_url,
                "prompt": rendered_prompt,
            },
            "logs": logs,
        }

    elif node_type == "document_generation":
        fmt = str(config.get("format", "docx")).lower()
        if fmt not in CONTENT_TYPES:
            fmt = "docx"

        raw_title = config.get("title", "Workflow Report")
        raw_content = config.get("content", "")

        rendered_title = str(render_template(raw_title, context))
        rendered_content = render_template(raw_content, context)

        logs.append(f"Compiling {fmt.upper()} document: '{rendered_title}'")
        data = await asyncio.to_thread(build_document, fmt, rendered_title, rendered_content)

        filename = safe_filename(rendered_title, fmt)
        file_id = str(uuid4())
        ext = EXTENSIONS.get(fmt, f".{fmt}")
        storage_path = build_key(user_id, conversation_id, file_id, ext)
        media_type = CONTENT_TYPES.get(fmt, "application/octet-stream")

        storage = get_storage()
        await storage.put(storage_path, data, media_type)

        record = GeneratedFile(
            id=file_id,
            user_id=user_id,
            conversation_id=conversation_id,
            filename=filename,
            format=fmt,
            media_type=media_type,
            size_bytes=len(data),
            storage_path=storage_path,
        )
        db.add(record)
        db.commit()

        download_url = f"/api/files/{file_id}/download"
        logs.append(f"Successfully generated {fmt.upper()} deliverable: {filename} ({len(data)} bytes)")
        return {
            "output": {
                "file_id": file_id,
                "filename": filename,
                "format": fmt,
                "size_bytes": len(data),
                "download_url": download_url,
            },
            "logs": logs,
        }

    else:
        logs.append(f"Generic passthrough node of type '{node_type}'.")
        return {"output": render_template(config, context), "logs": logs}


# ==============================================================================
# Full Workflow Execution Engine
# ==============================================================================

async def execute_workflow_run(run_id: str, user_id: str, api_key: str) -> None:
    """Execute all nodes of a workflow run in topological order, recording live progress."""
    logger.info("Executing workflow run %s for user %s", run_id, user_id)

    with db_session.SessionLocal() as db:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.user_id == user_id))
        if run is None:
            logger.error("Workflow run %s not found", run_id)
            return

        workflow = db.scalar(select(Workflow).where(Workflow.id == run.workflow_id))
        if workflow is None:
            # Check if it was an executive template
            template = get_template_by_id(run.workflow_id)
            if template:
                nodes = template.get("nodes", [])
                edges = template.get("edges", [])
                wf_name = template.get("name", "Template Workflow")
            else:
                run.status = "failed"
                run.error_message = "Referenced workflow definition does not exist."
                run.completed_at = utc_now()
                db.commit()
                return
        else:
            nodes = workflow.nodes or []
            edges = workflow.edges or []
            wf_name = workflow.name

        try:
            sorted_nodes = validate_and_sort_dag(nodes, edges)
        except Exception as exc:
            run.status = "failed"
            run.error_message = f"Invalid workflow DAG: {exc}"
            run.completed_at = utc_now()
            db.commit()
            return

        # Prepare execution state
        run.status = "running"
        run.started_at = utc_now()
        
        # Initialize step results with pending status
        step_results: dict[str, Any] = {}
        for n in sorted_nodes:
            step_results[n["id"]] = {
                "node_id": n["id"],
                "title": n.get("title", n["id"]),
                "type": n.get("type", "step"),
                "status": "pending",
                "logs": [],
                "output": None,
                "duration_ms": 0,
            }
        run.step_results = step_results
        run.outputs = {"files": [], "logs": []}
        db.commit()

        # Designate a conversation for file attachments
        conv = await _ensure_workflow_conversation(user_id, wf_name, db)
        conversation_id = conv.id

        # Context accessible to {{inputs.var}} and {{steps.node_id.output}}
        exec_context: dict[str, Any] = {
            "inputs": dict(run.inputs or {}),
            "steps": {},
        }

        generated_files: list[dict[str, Any]] = []

        # Execute nodes sequentially per topological sort
        for node in sorted_nodes:
            nid = node["id"]
            node_title = node.get("title", nid)
            step_results[nid]["status"] = "running"
            run.step_results = dict(step_results)
            db.commit()

            start_t = time.monotonic()
            try:
                result = await execute_node(
                    node=node,
                    context=exec_context,
                    user_id=user_id,
                    api_key=api_key,
                    conversation_id=conversation_id,
                    db=db,
                )
                dur_ms = int((time.monotonic() - start_t) * 1000)

                step_results[nid]["status"] = "success"
                step_results[nid]["output"] = result.get("output")
                step_results[nid]["logs"] = result.get("logs", [])
                step_results[nid]["duration_ms"] = dur_ms

                # Store into context for downstream steps
                exec_context["steps"][nid] = {
                    "output": result.get("output"),
                    "status": "success",
                }

                # Check if this node produced a downloadable file artifact
                output_val = result.get("output")
                if isinstance(output_val, dict) and output_val.get("file_id"):
                    file_item = {
                        "id": output_val["file_id"],
                        "node_id": nid,
                        "title": node_title,
                        "filename": output_val.get("filename", "file"),
                        "format": output_val.get("format", "bin"),
                        "size_bytes": output_val.get("size_bytes", 0),
                        "download_url": output_val.get("download_url", f"/api/files/{output_val['file_id']}/download"),
                    }
                    generated_files.append(file_item)

                run.step_results = dict(step_results)
                run.outputs = {
                    "files": generated_files,
                    "last_completed_step": nid,
                }
                db.commit()

            except Exception as exc:
                dur_ms = int((time.monotonic() - start_t) * 1000)
                logger.exception("Step %s failed in workflow run %s", nid, run_id)
                step_results[nid]["status"] = "failed"
                step_results[nid]["error"] = str(exc)
                step_results[nid]["duration_ms"] = dur_ms
                step_results[nid]["logs"] = step_results[nid].get("logs", []) + [f"Fatal step failure: {exc}"]

                run.status = "failed"
                run.error_message = f"Step '{node_title}' failed: {exc}"
                run.step_results = dict(step_results)
                run.completed_at = utc_now()
                db.commit()
                return

        # All steps succeeded!
        run.status = "success"
        run.completed_at = utc_now()
        run.outputs = {
            "files": generated_files,
            "total_steps": len(sorted_nodes),
            "deliverables_count": len(generated_files),
        }
        db.commit()
        logger.info("Workflow run %s completed successfully with %d deliverables", run_id, len(generated_files))
