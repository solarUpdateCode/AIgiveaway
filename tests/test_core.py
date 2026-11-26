"""Unit tests for AIgiveaway core logic (config, Gemini parser, safety guardrails)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.agent_engine import GiveawayAgentEngine
from app.config import AppConfig
from app.gemini_client import AgentDecision, parse_decision_json
from app.icon_gen import generate_ico


def test_config_roundtrip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg = AppConfig(
        api_key="test-key-local",
        giveaway_email="karankrajbhar23@gmail.com",
        target_url="https://cymatics.fm/",
        claimed_items=["Free Pack 1"],
    )
    cfg.save(cfg_file)
    loaded = AppConfig.load(cfg_file)
    assert loaded.api_key == "test-key-local"
    assert loaded.giveaway_email == "karankrajbhar23@gmail.com"
    assert loaded.claimed_items == ["Free Pack 1"]


def test_parse_decision_json_with_fences() -> None:
    raw = """```json
    {
      "page_state": "giveaway_popup",
      "priority": "giveaway",
      "action": "fill_giveaway",
      "answer_x_norm": 0.45,
      "answer_y_norm": 0.52,
      "email_x_norm": 0.45,
      "email_y_norm": 0.62,
      "submit_x_norm": 0.50,
      "submit_y_norm": 0.72,
      "giveaway_question": "What BPM is classic Trap?",
      "giveaway_answer": "140 BPM",
      "reason": "Giveaway popup detected"
    }
    ```"""
    dec = parse_decision_json(raw)
    assert dec.page_state == "giveaway_popup"
    assert dec.priority == "giveaway"
    assert dec.action == "fill_giveaway"
    assert dec.giveaway_answer == "140 BPM"
    assert dec.submit_x_norm == 0.50


def test_safety_blocks_paid_checkout() -> None:
    logs = []
    cfg = AppConfig(auto_checkout_free_only=True)
    engine = GiveawayAgentEngine(
        config=cfg,
        on_log=logs.append,
        on_status=lambda _: None,
        on_preview=lambda _: None,
        on_stats=lambda _: None,
    )
    mock_ctrl = MagicMock()
    engine._controller = mock_ctrl

    paid_decision = AgentDecision(
        page_state="checkout",
        priority="normal",
        action="click",
        x_norm=0.7,
        y_norm=0.8,
        cart_total_is_zero=False,
        reason="Total is $15.00",
    )
    engine._execute_decision(paid_decision)
    mock_ctrl.click_normalized.assert_not_called()
    assert any("SAFETY STOP" in m for m in logs)


def test_giveaway_fill_uses_configured_email() -> None:
    logs = []
    cfg = AppConfig(giveaway_email="karankrajbhar23@gmail.com", auto_answer_giveaway=True)
    engine = GiveawayAgentEngine(
        config=cfg,
        on_log=logs.append,
        on_status=lambda _: None,
        on_preview=lambda _: None,
        on_stats=lambda _: None,
    )
    mock_ctrl = MagicMock()
    engine._controller = mock_ctrl

    dec = AgentDecision(
        page_state="giveaway_popup",
        priority="giveaway",
        action="fill_giveaway",
        answer_x_norm=0.4,
        answer_y_norm=0.5,
        email_x_norm=0.4,
        email_y_norm=0.6,
        submit_x_norm=0.5,
        submit_y_norm=0.7,
        giveaway_question="Favorite DAW?",
        giveaway_answer="FL Studio",
    )
    engine._execute_decision(dec)
    typed_args = [call.args[0] for call in mock_ctrl.type_text.call_args_list]
    assert "FL Studio" in typed_args
    assert "karankrajbhar23@gmail.com" in typed_args
    assert engine.stats.giveaways_answered == 1


def test_icon_generator(tmp_path: Path) -> None:
    ico = generate_ico(tmp_path / "app.ico")
    assert ico.exists() and ico.stat().st_size > 1000
