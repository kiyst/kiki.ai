from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from training.personality.merge_adapter import main


ROOT = Path(__file__).resolve().parents[1]


def _run(monkeypatch: pytest.MonkeyPatch, adapter: Path, output: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["merge_adapter.py", "--adapter", str(adapter), "--output", str(output)],
    )
    main()


def test_merge_requires_adapter_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()

    with pytest.raises(SystemExit, match="2"):
        _run(monkeypatch, adapter, tmp_path / "merged")

    assert "adapter_config.json not found" in capsys.readouterr().err


def test_merge_rejects_wrong_base_before_loading_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(
        json.dumps({"base_model_name_or_path": "Qwen/not-the-trained-base"}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="2"):
        _run(monkeypatch, adapter, tmp_path / "merged")

    error = capsys.readouterr().err
    assert "adapter/base mismatch" in error
    assert "Qwen/Qwen3-4B-Instruct-2507" in error


def test_ollama_modelfile_preserves_qwen_chat_and_tool_roles() -> None:
    modelfile = (ROOT / "training/personality/Modelfile.qwen3").read_text(
        encoding="utf-8"
    )

    assert "{{ .Prompt }}" not in modelfile
    assert '<|im_start|>system' in modelfile
    assert '<|im_start|>user' in modelfile
    assert '<|im_start|>assistant' in modelfile
    assert "{{- if .Tools }}" in modelfile
    assert "PARAMETER stop <|im_end|>" in modelfile
