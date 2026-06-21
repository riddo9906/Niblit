from core.event_bus import Event, EventBus, EventType
from core.messages import Message, JsonMessageSerializer
from core.memory import InMemoryLongTermMemory, InMemoryReplayMemory, InMemoryShortTermMemory, InMemoryWorkingMemory
from core.tool_router import ToolRouter, LoggerTool, FileReaderTool
from core.simulation import SimulationHarness


def test_event_metadata_round_trip_and_type_name():
    event = Event(
        type=EventType.TASK_CREATED,
        payload={"goal": "demo"},
        source="test",
        runtime_id="rt-1",
        source_module="core",
        event_category="runtime",
        event_priority="high",
    )

    assert event.type_name == EventType.TASK_CREATED.value
    assert event.runtime_id == "rt-1"
    assert event.source_module == "core"
    assert event.event_category == "runtime"
    assert event.event_priority == "high"


def test_message_serializer_round_trip():
    serializer = JsonMessageSerializer()
    message = Message(
        message_type="request",
        source="agent-a",
        target="agent-b",
        payload={"topic": "planning"},
    )

    blob = serializer.serialize(message)
    restored = serializer.deserialize(blob)
    assert restored.message_type == "request"
    assert restored.payload["topic"] == "planning"


def test_in_memory_memory_layers_store_and_recall():
    short_term = InMemoryShortTermMemory()
    long_term = InMemoryLongTermMemory()
    working = InMemoryWorkingMemory()
    replay = InMemoryReplayMemory(max_items=2)

    short_term.write("topic", "alpha")
    long_term.write("topic", "beta")
    working.write("goal", "gamma")
    replay.append("event-1")
    replay.append("event-2")
    replay.append("event-3")

    assert short_term.read("topic") == "alpha"
    assert long_term.read("topic") == "beta"
    assert working.read("goal") == "gamma"
    assert replay.read()[-2:] == ["event-2", "event-3"]


def test_tool_router_dispatches_example_tools():
    router = ToolRouter()
    router.register_tool(LoggerTool())
    router.register_tool(FileReaderTool())

    logger_result = router.dispatch("logger", {"message": "hello"})
    file_result = router.dispatch("file_reader", {"path": "README.md"})

    assert logger_result["status"] == "ok"
    assert file_result["status"] == "ok"


def test_simulation_harness_replays_events():
    bus = EventBus(history_limit=10)
    harness = SimulationHarness(event_bus=bus)

    harness.generate_event("seed", {"value": 1})
    harness.generate_event("seed", {"value": 2})
    replayed = harness.replay_events()

    assert len(replayed) == 2
    assert [event.payload["value"] for event in replayed] == [1, 2]
