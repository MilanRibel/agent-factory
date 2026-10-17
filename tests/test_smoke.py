import pytest

import agent_factory


def test_main_prints_greeting(capsys: pytest.CaptureFixture[str]) -> None:
    agent_factory.main()

    assert "agent-factory" in capsys.readouterr().out
