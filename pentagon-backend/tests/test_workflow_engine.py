import pytest
from app.services.workflow_engine import (
    EXECUTIVE_TEMPLATES,
    get_nested_val,
    get_template_by_id,
    render_template,
    validate_and_sort_dag,
)


def test_get_nested_val():
    data = {
        "inputs": {"topic": "AI Security", "count": 5},
        "steps": {
            "s1": {
                "output": {"file_id": "xyz-123", "items": ["a", "b", "c"]}
            }
        },
    }
    assert get_nested_val(data, "inputs.topic") == "AI Security"
    assert get_nested_val(data, "inputs.count") == 5
    assert get_nested_val(data, "steps.s1.output.file_id") == "xyz-123"
    assert get_nested_val(data, "steps.s1.output.items.1") == "b"
    assert get_nested_val(data, "inputs.missing") is None


def test_render_template_string():
    ctx = {
        "inputs": {"name": "Pentagon", "version": "2.0"},
        "steps": {"n1": {"output": "Completed Analysis"}},
    }
    rendered = render_template("Welcome to {{inputs.name}} v{{inputs.version}}!", ctx)
    assert rendered == "Welcome to Pentagon v2.0!"

    rendered_exact = render_template("{{steps.n1.output}}", ctx)
    assert rendered_exact == "Completed Analysis"


def test_render_template_dict_and_list():
    ctx = {"inputs": {"title": "Doc Title", "val": 42}}
    template = {
        "title": "{{inputs.title}}",
        "items": ["Item: {{inputs.val}}", "{{inputs.title}}"],
    }
    res = render_template(template, ctx)
    assert res == {
        "title": "Doc Title",
        "items": ["Item: 42", "Doc Title"],
    }


def test_validate_and_sort_dag_linear():
    nodes = [
        {"id": "b", "title": "B"},
        {"id": "a", "title": "A"},
        {"id": "c", "title": "C"},
    ]
    edges = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "c"},
    ]
    sorted_nodes = validate_and_sort_dag(nodes, edges)
    order = [n["id"] for n in sorted_nodes]
    assert order == ["a", "b", "c"]


def test_validate_and_sort_dag_branch():
    nodes = [
        {"id": "start", "title": "Start"},
        {"id": "branch_1", "title": "Branch 1"},
        {"id": "branch_2", "title": "Branch 2"},
        {"id": "end", "title": "End"},
    ]
    edges = [
        {"source": "start", "target": "branch_1"},
        {"source": "start", "target": "branch_2"},
        {"source": "branch_1", "target": "end"},
        {"source": "branch_2", "target": "end"},
    ]
    sorted_nodes = validate_and_sort_dag(nodes, edges)
    order = [n["id"] for n in sorted_nodes]
    assert order[0] == "start"
    assert order[-1] == "end"
    assert set(order[1:3]) == {"branch_1", "branch_2"}


def test_validate_and_sort_dag_cycle():
    nodes = [
        {"id": "n1", "title": "Node 1"},
        {"id": "n2", "title": "Node 2"},
    ]
    edges = [
        {"source": "n1", "target": "n2"},
        {"source": "n2", "target": "n1"},
    ]
    with pytest.raises(ValueError, match="Workflow graph contains a dependency cycle"):
        validate_and_sort_dag(nodes, edges)


def test_executive_templates_validity():
    assert len(EXECUTIVE_TEMPLATES) >= 3
    for tpl in EXECUTIVE_TEMPLATES:
        assert "id" in tpl
        assert "name" in tpl
        assert "nodes" in tpl
        assert "edges" in tpl
        # Every template DAG must sort without error
        sorted_nodes = validate_and_sort_dag(tpl["nodes"], tpl["edges"])
        assert len(sorted_nodes) == len(tpl["nodes"])
        fetched = get_template_by_id(tpl["id"])
        assert fetched is not None
        assert fetched["name"] == tpl["name"]
