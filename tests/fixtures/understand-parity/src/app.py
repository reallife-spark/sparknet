"""Small parity fixture for the Python producer and Go adapters."""


def greet(name: str) -> str:
    return f"hi {name}"


class Greeter:
    def hello(self, name: str) -> str:
        return greet(name)
