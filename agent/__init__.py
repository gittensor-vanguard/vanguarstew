"""The vanguarstew maintainer agent (the miner-editable part).

Workflow: infer maintainer philosophy -> read situation -> plan/decide -> implement.

The agent produces prediction content only. Execution-receipt generation and verification
belong to the benchmark boundary, keeping provider-specific trust logic out of miner-editable
code.
"""
