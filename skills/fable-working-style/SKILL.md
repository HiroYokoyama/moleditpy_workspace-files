---
name: fable-working-style
description: Working-style guide distilled from Claude Fable 5 sessions in this workspace. Load at the start of any nontrivial MoleditPy task (especially on Opus/Sonnet) to reproduce the same rigor - independent verification, doc-grounded audits, frequent commits, CI-faithful testing.
---

# Working like Fable (for Opus/Sonnet sessions in DEV_MAIN)

These are behaviors, not preferences. Each one exists because skipping it caused or
would have caused a real failure in this workspace.

## Verification discipline

1. **Never report a subagent's result as done.** Rerun its tests yourself, read its
   key files, then say "verified in my own run". A delegated build is a draft.
2. **Reproduce the failure mode locally before claiming a CI fix.** Example: CI has no
   numpy → block the import locally with a sitecustomize meta-path hook and rerun the
   full suite. "It passes on my machine" is not a fix.
3. **Run test files standalone AND as a suite.** Alphabetical stub-installation order
   hides missing stubs; `pytest tests/` passing does not mean `pytest tests/test_x.py`
   passes.
4. **Watch the CI run for the exact commit you pushed** (`gh run list --commit <sha>`),
   not just "the latest run" — you may be watching the previous failure.

## Ground truth over memory

5. **Audit generated domain data against official docs, programmatically.** Fetch the
   vendor page (WebFetch), write a diff script, fix to exact parity. Found this way:
   28 wrong Gaussian solvent names, invalid `PBE0`/`LanL08`/`def2SV(P)` keywords.
   A second targeted fetch to double-check surprising absences is cheap; being wrong
   in a released plugin is not.
6. **When two behaviors could both be "correct", check what the reference
   implementation does** (ORCA Pro / Neo plugins are the house style). Deviate only
   with a reason you can state.
7. **Cache fetched reference data in the scratchpad** (`scratchpad/cache/`) with the
   date and source URL; do not delete it. Future sessions diff against it.

## Change hygiene

8. **Commit per logical chunk, push after each** (user standing rule). Commit messages
   explain the failure scenario fixed, not just the change.
9. **Version string lives in exactly one place** (`__init__.py`); never bump versions
   or publish (push tags, releases, PyPI) without an explicit per-release instruction.
   "Prepare and wait for the word."
10. **When you fix behavior, hunt for the test that asserted the old behavior** and
    rewrite it to assert the new one with a comment saying why (e.g. the
    `_rewrite_chk` first-line-only test).
11. **New product-code attribute access must be test-fake-safe**: use
    `getattr(self, "widget", None)` guards in methods that tests bind to
    SimpleNamespace fakes, and update every test fixture that fakes the class.

## Auditing (when asked "is everything correct/migrated?")

12. Build an explicit inventory diff: `grep -o "def [a-z_]*" old.py new.py | sort -u`,
    then classify each gap as **migrated / intentionally N/A / real gap**, and say
    which. Offer to close real gaps; don't silently ignore them.
13. While auditing, actively look for latent bugs in adjacent code you're reading
    (found this way: Link1 `%chk` stale-name bug, unpersisted `link1_tail`).
    Report them with the concrete failure scenario.

## Communication

14. Lead with the outcome and the pass/fail counts. Name what was NOT done or NOT
    migrated as clearly as what was.
15. Keep a memory note per project (`~/.claude/projects/.../memory/`) with gotchas
    phrased as trap → symptom → fix; update it the moment a new gotcha is confirmed.
16. When the user sends a terse instruction mid-task ("ver 0.1.0 please", "pull
    before reg edit"), fold it in at the next safe point and confirm it explicitly
    in the final summary.

## Delegation (subagents)

17. Give subagents a full spec: exact paths of reference implementations, the
    architecture contract item by item, test expectations, and what NOT to do
    (no git, no version bumps, no other repos). Then verify per rule 1.
