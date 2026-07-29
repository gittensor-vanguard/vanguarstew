# Plan 080 — run transcript

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1990

Maps the [spec](./spec.md) onto `benchmark/transcript.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_080_transcript.py` |
| ------------ | -------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Canonical serialization | `test_canonical_json_sorts_keys_and_drops_whitespace`, `test_canonical_json_escapes_non_ascii`, `test_canonical_json_stringifies_an_unserializable_value`, `test_canonical_json_collapses_distinct_objects_with_equal_str`, `test_canonical_json_is_not_process_stable_for_identity_bearing_str` |
| Digest primitive | `test_digest_pins_literal_hexes`, `test_digest_ignores_dict_insertion_order` |
| Replay key | `test_request_key_is_the_digest_of_the_keyed_fields_only`, `test_request_key_ignores_transport_fields`, `test_request_key_changes_with_each_keyed_field`, `test_request_key_treats_an_absent_keyed_field_as_none`, `test_request_key_warns_and_keys_verbatim_for_a_non_dict` |
| Construction | `test_init_coerces_falsy_entries_to_empty`, `test_init_is_not_the_tolerant_path` |
| Recording | `test_record_appends_the_documented_row_shape`, `test_record_stores_the_caller_object_so_a_later_mutation_desyncs_the_key`, `test_record_drops_a_non_dict_request_body_but_keeps_its_key` |
| Ordered replay | `test_replay_serves_repeated_requests_in_recorded_order`, `test_unmatched_request_misses_silently`, `test_exhausted_key_warns_and_misses`, `test_row_without_a_response_replays_none`, `test_row_without_a_key_never_matches`, `test_reset_rewinds_cursors_without_touching_entries` |
| Size and serialization | `test_len_counts_unreplayable_entries`, `test_to_dict_shape_is_pinned`, `test_save_writes_readable_json_and_load_round_trips` |
| Tolerant load | `test_from_dict_warns_on_a_non_dict_file`, `test_from_dict_warns_on_non_list_entries`, `test_from_dict_is_silent_when_entries_is_absent_or_none`, `test_from_dict_drops_non_dict_rows_without_warning`, `test_from_dict_keeps_a_contentless_row`, `test_from_dict_ignores_the_declared_version` |
| Transcript identity | `test_store_digest_is_keys_and_responses_only`, `test_store_digest_ignores_a_cosmetic_request_body_change`, `test_store_digest_changes_with_recorded_order`, `test_store_digest_changes_with_an_unreplayable_row` |
| Pure evaluation | `test_replay_does_not_mutate_entries_or_request` |

## Verification strategy

One contract-test group per EARS section; every miss / exhaustion / non-dict / malformed-file /
unkeyed-row branch called out in the spec has an asserting test (lessons from the Spec 057 / 059
rejections and the finding lists on the closed Spec 068 / 069 PRs). Expectations are **literal** —
exact serializations (`{"a":2,"b":1}`) and exact `sha256` hexes
(`digest({})` → `44136fa3…caaff8a`) — rather than re-derived from the module, so a change to the
canonical form fails loudly instead of silently agreeing with itself. The three logging branches
(`request_key` on a non-dict, `replay` exhaustion, `from_dict` on a non-dict file / non-list
`entries`) are asserted via `caplog` on the `benchmark.transcript` logger, and the two **silent**
branches (an ordinary replay miss; an absent/`None` `entries`) assert the absence of a warning —
otherwise "silent" is untested and a future warning would pass unnoticed.

The `default=str` boundary is verified positively rather than assumed away: one test fixes two
distinct instances of a class whose `__str__` is constant and asserts they collapse to the *same*
key, and one asserts a plain `object()` — whose `str()` carries a process-local address — produces
*different* digests for different instances. Both pin where the module's stability guarantee stops,
which is exactly the part a verifier has to know.

`save`/`load` are exercised against a real `tmp_path` file (the module's only I/O), asserting the
on-disk form is the readable `indent=1, sort_keys=True` JSON rather than the canonical form, and
that a round trip preserves replay order. Integration coverage — the replay proxy driving
`agent/llm.py`, and the attestation binding — stays in `tests/test_transcript.py`.
