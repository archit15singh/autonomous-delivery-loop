# Canary health from Prometheus

Collect read-only operational evidence after the candidate and control are
deployed. Select a trusted Prometheus origin with two cumulative counters,
total requests and successful requests. Both must expose the exact
`revision` and `deployment` labels. Use one aggregated series per cohort and
metric. Exporters should publish both counters atomically. Prefer an
independent ingress or probe exporter as the source.

The operator supplies a version 1 JSON policy. The fields are
`requests_metric`, `successes_metric`, `step_seconds`, `minimum_requests`,
`minimum_success_rate`, `max_success_rate_drop`, `candidate` and `control`.
Each cohort identifies a full Git `revision` and a distinct `deployment` ID.
Set the observation window in UTC epoch seconds. The collector checks freshness,
coverage, counter continuity, identity, sample count and both success rates.

```sh
python3 -m delivery factory --output canary.json canary-observe \
  --policy canary-policy.json --origin https://prometheus.example \
  --start "$START" --end "$END" --token-env ADL_PROMETHEUS_TOKEN
```

A healthy result is eligible for operator promotion review. A candidate-only
regression is eligible for operator rollback review. Missing data, stale samples,
counter resets and an unhealthy control all leave the rollout on hold. This
command has read-only metrics access. Promotion and rollback continue through
the existing deployment approvals for the exact release target.

The hosted drill uses real requests observed by a separate probe loop and a
pinned Prometheus server. It flips only the candidate HTTP handler to 503,
then checks both receipts. The drill uses a disposable runner.
