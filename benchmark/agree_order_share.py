"""Report the agree outcome share from a replay artifact's judge order stats.

Thin binding over :mod:`benchmark.order_share` — see there for the shared implementation
and the full contract. This module is a named entry point for its CLI and callers; the
per-slice helper and validators are re-exported for direct use.
"""

from __future__ import annotations

from benchmark.order_share import (  # noqa: F401  (re-exported for callers/tests)
    _dict,
    _is_int,
    _is_number,
    _order_stats,
    make_order_share,
)

summarize_agree_order_share, agree_order_share_headline, _slice_summary = make_order_share(
    numerator_keys=("agree",),
    count_field="agree",
    share_field="agree_order_share",
    headline_label="agree-order share",
)

__all__ = [
    "summarize_agree_order_share", "agree_order_share_headline", "_slice_summary",
    "_dict", "_is_int", "_is_number", "_order_stats",
]
