---
name: deliver-outcome
description: Use when a delivery brief names an outcome and independent verification requirements.
---

1. Read the brief and target repository instructions. Identify the observable behavior and the checks to run.
2. When practical, reproduce the outcome with a focused test and confirm it fails before changing implementation. Reuse the nearest test suite. Write the smallest change that makes the behavior pass.
3. Run the focused check and relevant existing regression checks. Use the test interpreter in the brief. Fix actionable failures within its limits.
4. Leave the implementation and any regression test in the checkout. Report commands, observed results, and checks still pending. A trusted grader or release owner supplies independent verification.
