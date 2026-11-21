---
name: factory-cold-review
description: Independently review an owned factory pull request against its exact base and candidate.
---

Look for demonstrable defects in behavior, state transitions, recovery or compatibility. Read the proposed change against the trusted base. Explain the failing scenario and name the path that needs attention. Return an empty list when the evidence supports no actionable finding. Keep style preferences out of the findings. A human reviewer can correct a finding by identifying its exact review and giving a rationale.
