"""The evaluation harness: YAML tasks, a deterministic mock LLM, and a runner.

The mock suite is deterministic and runs in CI; ``--live`` spends real NVIDIA
requests and is only ever run by a human. Tasks live in ``tasks/*.yaml``.
"""
