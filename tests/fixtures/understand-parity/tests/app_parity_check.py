from src.app import greet


def test_greet():
    assert greet("parity") == "hi parity"
