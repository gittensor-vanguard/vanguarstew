# Plan 008 — agent philosophy inference

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #672

Maps the [spec](./spec.md) onto `agent/philosophy.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_008_philosophy.py` |
| ------------ | -------------------------------------------- |
| Constants | `test_offline_stub_is_pinned`, `test_system_prompt_states_the_task_and_json_only_contract`, `test_fewshot_carries_two_contrasting_valid_examples` |
| Text-field normalization | `test_normalize_text_returns_default_only_for_none`, `test_normalize_text_returns_a_string_verbatim`, `test_normalize_text_coerces_every_non_string` |
| List-field normalization | `test_normalize_string_list_none_is_empty`, `test_normalize_string_list_wraps_a_bare_string`, `test_normalize_string_list_drops_a_blank_string`, `test_normalize_string_list_skips_none_and_blank_entries`, `test_normalize_string_list_keeps_falsy_non_none_entries`, `test_normalize_string_list_stringifies_nested_containers`, `test_normalize_string_list_rejects_a_non_list_container` |
| Philosophy mapping | `test_normalize_philosophy_coerces_a_non_dict_payload_to_the_stub`, `test_normalize_philosophy_maps_every_documented_field`, `test_normalize_philosophy_falls_back_per_field`, `test_normalize_philosophy_drops_extra_keys`, `test_normalize_philosophy_stub_copy_is_shallow` |
| Inference | `test_infer_philosophy_non_dict_context_skips_the_llm_entirely`, `test_infer_philosophy_calls_chat_json_once_with_the_stub`, `test_infer_philosophy_normalizes_an_unusable_payload`, `test_infer_philosophy_prompt_carries_the_documented_sections` |
| Offline determinism | `test_offline_result_is_the_normalized_stub`, `test_offline_result_is_identical_across_calls_and_contexts`, `test_offline_result_is_a_fresh_top_level_dict` |
| Rendering | `test_render_keeps_the_whitelist_in_order`, `test_render_marks_missing_keys_null`, `test_render_is_truncated_at_the_prompt_budget` |

## Verification strategy

One contract-test group per EARS section. Every branch the closed prior submission was rejected for
leaving untested is covered by a **dedicated** test here: the non-dict LLM payload
(`test_normalize_philosophy_coerces_a_non_dict_payload_to_the_stub`, parameterized over `None`, a
list, a string and a number), bare-string wrapping
(`test_normalize_string_list_wraps_a_bare_string`), blank and skipped list entries
(`test_normalize_string_list_drops_a_blank_string`,
`test_normalize_string_list_skips_none_and_blank_entries`), non-string text coercion
(`test_normalize_text_coerces_every_non_string`), the `None` text fallback
(`test_normalize_text_returns_default_only_for_none`), and the non-dict context fallback
(`test_infer_philosophy_non_dict_context_skips_the_llm_entirely`, which also asserts the LLM is
never called). The offline-determinism criterion is stated in full in the spec and pinned by three
tests rather than left as prose.

Expectations are **literal** — the exact stub dict, the exact coerced strings (`str(0)` → `"0"`,
`str(False)` → `"False"`, `str(["n"])` → `"['n']"`), and the exact 12000-character render cap —
rather than re-derived from the module, so a change in the normalizers fails loudly instead of
silently agreeing with itself. Two easy-to-miss edges get their own assertions because they are
where a "reasonable" refactor would break a consumer: an **empty** string is *not* the `None`
fallback (only `None` is), and falsy non-`None` list entries (`0`, `False`) survive because their
string form is not blank while `""` and `"  "` do not.

`infer_philosophy` is driven by small recording doubles rather than mocks, so the call count, the
`stub` argument identity and the assembled prompt are all observed on the real code path;
`context_for_agent` and `chat_json` are exercised for real (their own contracts are Specs 003 and
010) rather than stubbed out. The shared-list caveat is asserted with `is` on the returned
`values`/`evidence` and restored afterwards so the module-level stub is left untouched for other
tests. Broader behavioral coverage stays in `tests/test_philosophy.py`.
