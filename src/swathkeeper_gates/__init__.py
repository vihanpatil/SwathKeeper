"""swathkeeper-gates: pre-registered evidence gates over flight logs (docs/design/GATES_TOOL_DESIGN.md).

A stranger's log and a YAML file of bars hashed before the run go in; a JSON verdict and an exit code
come out, and "could not tell" is a fourth word, never a green. Core = stdlib + PyYAML; the binary
parsers are extras ([ardupilot] = pymavlink). Nothing here imports `fieldguard_planning`, and nothing
there imports this (design §1; AST-pinned in tests/test_gates_cli.py).
"""
__version__ = "0.1.0"
CONTRACT = "swathkeeper-flightlog/1.0"
