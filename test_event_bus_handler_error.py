from modules.event_bus import EventBus, NiblitEvent


def test_publish_continues_after_handler_error() -> None:
    bus = EventBus()
    seen: list[str] = []

    def failing_handler(event: NiblitEvent) -> None:
        raise RuntimeError("boom")

    def good_handler(event: NiblitEvent) -> None:
        seen.append(event.type)

    bus.subscribe("demo.event", failing_handler)
    bus.subscribe("demo.event", good_handler)

    bus.publish(NiblitEvent(type="demo.event", source="test", payload={"ok": True}))

    assert seen == ["demo.event"]
