"""Demo module for testing Shipyard's surgical editing.

This file exists solely for safe agent testing — it is not part of the
production codebase.
"""


def greet(name: str) -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed)."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
