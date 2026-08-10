Plan: Add input validation to the pricing helper
Objective: Reject negative or over-100 discount percentages in `apply_discount` before they reach production.
Steps:
- [ ] 1. Add a `ValueError` guard for `discount_percent < 0` or `discount_percent > 100` in `apply_discount`.
- [ ] 2. Add unit tests covering the new validation (valid boundary, negative, over 100).
- [ ] 3. Run the full test suite and confirm no regressions.
Dependencies: Step 2 depends on step 1. Step 3 depends on steps 1 and 2.
Acceptance checks:
- `apply_discount` raises `ValueError` for out-of-range input.
- Existing valid-input behavior is unchanged.
- Full test suite passes.
Relevant invariants: Preserve the approved objective. Do not skip verification.
Allowed files/surfaces: pricing.py and its test file only.
Verification: `python -m pytest`.
Escalation triggers: None expected; escalate only if the acceptance checks conflict with existing callers of `apply_discount`.
