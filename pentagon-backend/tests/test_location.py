"""Location: that it stays off unless enabled, that the browser is preferred,
and that every failure path ends without a position rather than a guess."""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.services import chat_graph, location
from app.services.command_runner import CommandRegistry


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    fresh = CommandRegistry()
    monkeypatch.setattr(location, "REGISTRY", fresh)
    monkeypatch.setattr(location, "_cached_ip_location", None)
    return fresh


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "location_enabled", True)
    monkeypatch.setattr(settings, "command_tool_enabled", True)


def _no_browser(monkeypatch, fallback):
    """Stand in for the browser lookup returning nothing."""

    async def ask(*_args, **_kwargs):
        return None

    async def ip():
        return fallback

    monkeypatch.setattr(location, "ask_the_client_for_location", ask)
    monkeypatch.setattr(location, "_lookup_ip_location", ip)


def test_location_is_off_by_default():
    """The *code* default is off, whatever the local .env happens to say.

    Asserting on the loaded settings would just re-read whatever the developer
    has enabled locally, which is not the property that matters.
    """
    from app.config import Settings

    assert Settings.model_fields["location_enabled"].default is False


def test_tool_refuses_when_the_server_switch_is_off(monkeypatch):
    monkeypatch.setattr(settings, "location_enabled", False)
    result = asyncio.run(
        location.run_location_tool({}, conversation_id="c", user_id="u")
    )
    assert result.exit_code == 1
    assert "switched off" in result.stderr
    assert location.REGISTRY._requests == {}


def test_browser_answer_is_preferred_over_the_network(monkeypatch):
    _enable(monkeypatch)
    used = []

    async def ip():
        used.append("ip")
        return None

    monkeypatch.setattr(location, "_lookup_ip_location", ip)

    async def scenario():
        task = asyncio.create_task(
            location.run_location_tool({}, conversation_id="c", user_id="u")
        )
        for _ in range(400):
            if location.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        request = list(location.REGISTRY._requests.values())[0]
        assert request.kind == "location"
        assert request.detail == ""
        # This is exactly what POST /api/commands/decide does with a value.
        location.REGISTRY.resolve(
            request.request_id,
            "u",
            True,
            {"latitude": 28.6542, "longitude": 77.2373, "accuracy_m": 40.0},
        )
        return await task

    result = asyncio.run(scenario())
    assert used == [], "it fell back to the network when the browser answered"
    assert result.ok
    assert "28.65420, 77.23730" in result.stdout
    assert "browser geolocation" in result.stdout
    assert result.value["source"] == "browser geolocation"


def test_declining_falls_back_to_the_network(monkeypatch):
    _enable(monkeypatch)
    fallback = location.Location(
        latitude=28.65, longitude=77.23, accuracy_m=None,
        source="ip (approximate, no GPS hardware on this machine)",
        label="Delhi, India",
    )
    _no_browser(monkeypatch, fallback)
    result = asyncio.run(
        location.run_location_tool({}, conversation_id="c", user_id="u")
    )
    assert result.ok
    assert "Delhi, India" in result.stdout
    # The source is always disclosed, so a coarse fix is never passed off as
    # a satellite one.
    assert "Source:" in result.stdout
    assert "no GPS hardware" in result.stdout


def test_no_answer_anywhere_reports_failure_rather_than_guessing(monkeypatch):
    _enable(monkeypatch)
    _no_browser(monkeypatch, None)
    result = asyncio.run(
        location.run_location_tool({}, conversation_id="c", user_id="u")
    )
    assert result.exit_code == 1
    assert "guessing" in result.stderr
    assert result.value == {}


def test_an_unanswerable_coordinate_is_rejected(monkeypatch):
    for bad in (
        {"latitude": 91.0, "longitude": 0.0},
        {"latitude": 0.0, "longitude": 181.0},
        {"latitude": "north", "longitude": "west"},
        {},
    ):
        assert location._valid_coordinate(bad) is None, bad
    assert location._valid_coordinate(
        {"latitude": 28.6542, "longitude": 77.2373, "accuracy_m": 12}
    ) == (28.6542, 77.2373, 12.0)


def test_bad_coordinates_from_the_client_are_not_returned(monkeypatch):
    """A hostile or broken client must not get a position into the model."""
    _enable(monkeypatch)

    async def ip():
        return None

    monkeypatch.setattr(location, "_lookup_ip_location", ip)

    async def scenario():
        task = asyncio.create_task(
            location.run_location_tool({}, conversation_id="c", user_id="u")
        )
        for _ in range(400):
            if location.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        request = list(location.REGISTRY._requests.values())[0]
        location.REGISTRY.resolve(
            request.request_id, "u", True, {"latitude": 999, "longitude": 999}
        )
        return await task

    result = asyncio.run(scenario())
    assert result.exit_code == 1
    assert result.value == {}


def test_another_user_cannot_supply_the_coordinates(monkeypatch):
    _enable(monkeypatch)

    async def ip():
        return None

    monkeypatch.setattr(location, "_lookup_ip_location", ip)
    seen = {}

    async def scenario():
        task = asyncio.create_task(
            location.run_location_tool({}, conversation_id="c", user_id="owner")
        )
        for _ in range(400):
            if location.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        request = list(location.REGISTRY._requests.values())[0]
        seen["attacker"] = location.REGISTRY.resolve(
            request.request_id, "attacker", True,
            {"latitude": 1.0, "longitude": 1.0},
        )
        location.REGISTRY.resolve(
            request.request_id, "owner", True,
            {"latitude": 28.6542, "longitude": 77.2373},
        )
        return await task

    result = asyncio.run(scenario())
    assert seen["attacker"] is False
    assert result.ok
    assert "28.65420" in result.stdout


def test_the_tool_is_absent_when_the_switch_is_off(monkeypatch):
    from langchain_core.messages import AIMessage

    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "location_enabled", False)
    model = _RecordingModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)
    graph = chat_graph.build_chat_graph(
        "k", "m", user_id="u", use_web_search=False, command_tool_enabled=True
    )
    asyncio.run(graph.ainvoke(chat_graph.initial_chat_state(
        user_id="u", conversation_id="c", message="where am i",
        history=[], use_web_search=False, command_tool_enabled=True,
    )))
    assert "get_location" not in model.bound


def test_the_tool_appears_when_both_switches_are_on(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "desktop_actions_enabled", False)
    model = _RecordingModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)
    graph = chat_graph.build_chat_graph(
        "k", "m", user_id="u", use_web_search=False, command_tool_enabled=True
    )
    asyncio.run(graph.ainvoke(chat_graph.initial_chat_state(
        user_id="u", conversation_id="c", message="where am i",
        history=[], use_web_search=False, command_tool_enabled=True,
    )))
    assert "get_location" in model.bound


class _RecordingModel:
    def __init__(self):
        from langchain_core.messages import AIMessage

        self.messages = [AIMessage(content="ok")]
        self.bound = []

    def bind_tools(self, tools):
        self.bound = [
            t.get("function", {}).get("name") if isinstance(t, dict) else getattr(t, "name", None)
            for t in tools
        ]
        return self

    async def ainvoke(self, messages, config=None):
        return self.messages.pop(0) if self.messages else AIMessage(content="done")