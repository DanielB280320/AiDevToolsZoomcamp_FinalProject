"""Throwaway: demonstrates that a failing test fails CI (#11). Never merged."""


def test_ci_demo_failure() -> None:
    assert 1 + 1 == 3
