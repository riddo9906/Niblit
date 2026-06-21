from core.messages import (
    AIRequest,
    MarketSnapshot,
    Message,
    RiskAssessment,
    StandardEventType,
)


def test_message_round_trip_preserves_contract_metadata():
    message = Message(
        message_type=StandardEventType.AI_INFERENCE_REQUESTED,
        source="niblit",
        target="niblit-cloud-server",
        schema_version="1.0",
        correlation_id="corr-123",
        payload={"request_id": "req-123"},
    )

    restored = Message.from_dict(message.to_dict())

    assert restored.message_type == StandardEventType.AI_INFERENCE_REQUESTED
    assert restored.schema_version == "1.0"
    assert restored.correlation_id == "corr-123"
    assert restored.payload["request_id"] == "req-123"


def test_market_snapshot_and_ai_request_models_round_trip():
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=50000.0, volume=123.4)
    request = AIRequest(model_id="local", prompt="Analyze the market", market_snapshot=snapshot)

    assert snapshot.to_dict()["symbol"] == "BTCUSDT"
    assert request.to_dict()["market_snapshot"]["price"] == 50000.0
    assert request.to_dict()["model_id"] == "local"


def test_risk_assessment_serializes_with_confidence_and_level():
    assessment = RiskAssessment(level="medium", confidence=0.82, rationale="Volatility spike")

    payload = assessment.to_dict()

    assert payload["level"] == "medium"
    assert payload["confidence"] == 0.82
    assert payload["rationale"] == "Volatility spike"
