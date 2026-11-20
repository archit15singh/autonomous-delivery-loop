"""Evaluate a completed observation supplied by an independent metrics producer."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ImpactPolicy:
    source: str
    metric: str
    cohort: str
    minimum_samples: int
    minimum_window_seconds: int
    minimum_success_rate: float

    @classmethod
    def read(cls, data):
        if not isinstance(data, dict) or data.keys() != cls.__dataclass_fields__.keys():
            raise ValueError("impact policy needs source, metric, cohort, window, sample and rate")
        for key in ("source", "metric", "cohort"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError(f"impact {key} must be non-empty")
        for key in ("minimum_samples", "minimum_window_seconds"):
            if type(data[key]) is not int or data[key] < 1:
                raise ValueError(f"impact {key} must be a positive integer")
        rate = data["minimum_success_rate"]
        if type(rate) not in (int, float) or not 0 <= rate <= 1:
            raise ValueError("impact minimum_success_rate must be between 0 and 1")
        return cls(**data)


def impact_verdict(policy, evidence, revision, deployment):
    if policy is None:
        return {"verdict": "not_required"}
    if evidence is None:
        return {"verdict": "inconclusive", "reason": "impact_evidence_missing"}
    expected = {"revision": revision, "deployment": deployment, "source": policy.source,
                "metric": policy.metric, "cohort": policy.cohort}
    if not isinstance(evidence, dict) or any(evidence.get(k) != v for k, v in expected.items()):
        return {"verdict": "inconclusive", "reason": "impact_identity_mismatch"}
    try:
        start = datetime.fromisoformat(evidence["started_at"])
        end = datetime.fromisoformat(evidence["ended_at"])
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("observation timestamps must have timezones")
        duration = (end - start).total_seconds()
        samples, successes = evidence["samples"], evidence["successes"]
        if (duration <= 0 or type(samples) is not int or type(successes) is not int
                or not 0 <= successes <= samples):
            raise ValueError("invalid observation")
    except (KeyError, ValueError, TypeError):
        return {"verdict": "inconclusive", "reason": "impact_evidence_invalid"}
    observations = {**expected, "started_at": start.isoformat(), "ended_at": end.isoformat(),
                    "samples": samples, "successes": successes}
    if samples < policy.minimum_samples or duration < policy.minimum_window_seconds:
        return {"verdict": "inconclusive", "reason": "impact_observation_insufficient",
                **observations}
    rate = successes / samples
    return {"verdict": "verified" if rate >= policy.minimum_success_rate else "failed",
            "reason": "impact_threshold_passed" if rate >= policy.minimum_success_rate else "impact_threshold_failed",
            "success_rate": rate, **observations}
