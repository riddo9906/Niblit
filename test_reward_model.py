"""Unit tests for modules.reward_model."""

from unittest.mock import MagicMock, patch

import pytest

import modules.reward_model as reward_model

pytestmark = pytest.mark.skipif(
    not reward_model._TRANSFORMERS_AVAILABLE,
    reason="transformers not installed",
)


def test_default_classifier_model_constant_is_used():
    from modules.reward_model import _DEFAULT_CLASSIFIER_MODEL, RewardModel

    rm = RewardModel()
    assert rm._model_name == _DEFAULT_CLASSIFIER_MODEL


def test_get_pipeline_builds_explicit_model_and_tokenizer():
    tokenizer_obj = object()
    model_obj = object()
    pipeline_obj = object()

    tokenizer_ctor = MagicMock(return_value=tokenizer_obj)
    model_ctor = MagicMock(return_value=model_obj)
    pipeline_ctor = MagicMock(return_value=pipeline_obj)

    with (
        patch.object(reward_model._AutoTokenizer, "from_pretrained", tokenizer_ctor),
        patch.object(reward_model._AutoModelForSeqClass, "from_pretrained", model_ctor),
        patch.object(reward_model, "_hf_pipeline", pipeline_ctor),
    ):
        rm = reward_model.RewardModel(model_name="my-seq-model")
        loaded = rm._get_pipeline()
        assert loaded is pipeline_obj
        tokenizer_ctor.assert_called_once_with("my-seq-model")
        model_ctor.assert_called_once_with("my-seq-model")
        pipeline_ctor.assert_called_once()
        _, kwargs = pipeline_ctor.call_args
        assert kwargs["model"] is model_obj
        assert kwargs["tokenizer"] is tokenizer_obj
        assert kwargs["device"] == -1


def test_get_pipeline_failure_falls_back_to_none():
    with patch.object(reward_model._AutoTokenizer, "from_pretrained", side_effect=RuntimeError("boom")):
        rm = reward_model.RewardModel(model_name="broken-model")
        assert rm._get_pipeline() is None
