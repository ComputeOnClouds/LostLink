# LostLink evaluation harness

Scaffold placeholder (Task 1). Built in Tasks 13-14.

Will contain:
- **Ground-truth generation** — Claude-generated lost/found descriptions with
  distractors, plus a small set of real photographed objects.
- **Matching-quality metrics** — Hit@1, Recall@5, MRR across variants (text-only,
  text+location, text+location+time; image variants once Option 2 is enabled). Imports
  the pure `BlendedScorer` from `backend/pipeline` and sweeps weight maps in memory
  (RATIONALE ADR-005).
- **Notification metrics** — alert precision, false-alert rate, missed-notification
  rate, latency.
- **System/cost tooling** (Task 14) — load test (latency/throughput/queue time) and a
  script that reads `cdk synth` output to enumerate billable resources.
