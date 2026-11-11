"""Small, dependency-free statistics used for agreement and quantitative synthesis."""

from __future__ import annotations

import math
from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# Agreement and classification metrics
# --------------------------------------------------------------------------- #


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa for two raters. None when undefined (no items or no variance)."""
    if not a or len(a) != len(b):
        return None
    n = len(a)
    labels = sorted(set(a) | set(b))
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    if math.isclose(expected, 1.0):
        return None
    return (observed - expected) / (1 - expected)


def kappa_label(kappa: float | None) -> str:
    """Landis & Koch (1977) verbal interpretation."""
    if kappa is None:
        return "undefined"
    for bound, label in [(0.0, "poor"), (0.2, "slight"), (0.4, "fair"), (0.6, "moderate"), (0.8, "substantial")]:
        if kappa <= bound:
            return label
    return "almost perfect"


def classification_metrics(predicted: list[bool], truth: list[bool]) -> dict[str, float | int | None]:
    tp = sum(p and t for p, t in zip(predicted, truth))
    fp = sum(p and not t for p, t in zip(predicted, truth))
    fn = sum(not p and t for p, t in zip(predicted, truth))
    tn = sum(not p and not t for p, t in zip(predicted, truth))
    n = tp + fp + fn + tn

    def ratio(num: float, den: float) -> float | None:
        return round(num / den, 4) if den else None

    recall = ratio(tp, tp + fn)
    precision = ratio(tp, tp + fp)
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision and recall
        else (0.0 if precision is not None and recall is not None else None)
    )
    # Work saved over sampling: share of records a human no longer has to read,
    # corrected for the recall achieved (Cohen et al. 2006).
    wss = round((tn + fn) / n - (1 - recall), 4) if n and recall is not None else None
    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall_sensitivity": recall,
        "precision": precision,
        "specificity": ratio(tn, tn + fp),
        "f1": f1,
        "accuracy": ratio(tp + tn, n),
        "work_saved_over_sampling": wss,
    }


# --------------------------------------------------------------------------- #
# Meta-analysis (inverse variance, DerSimonian-Laird random effects)
# --------------------------------------------------------------------------- #

RATIO_MEASURES = {"OR", "RR", "HR", "IRR", "DOR"}
Z95 = 1.959963984540054


@dataclass
class StudyEffect:
    label: str
    estimate: float  # on the analysis scale (log scale for ratio measures)
    se: float


@dataclass
class PooledResult:
    k: int
    fixed: float
    fixed_ci: tuple[float, float]
    random: float
    random_ci: tuple[float, float]
    tau2: float
    q: float
    i2: float
    log_scale: bool

    def as_dict(self) -> dict:
        back = math.exp if self.log_scale else (lambda x: x)
        return {
            "k": self.k,
            "fixed_effect": round(back(self.fixed), 4),
            "fixed_ci": [round(back(v), 4) for v in self.fixed_ci],
            "random_effects": round(back(self.random), 4),
            "random_ci": [round(back(v), 4) for v in self.random_ci],
            "tau2": round(self.tau2, 5),
            "Q": round(self.q, 3),
            "I2_percent": round(self.i2, 1),
            "scale": "log (back-transformed)" if self.log_scale else "natural",
        }


def effect_from_ci(value: float, ci_low: float, ci_high: float, measure: str) -> tuple[float, float] | None:
    """Convert an estimate with a 95 % CI to (estimate, standard error) on the analysis scale."""
    if measure.upper() in RATIO_MEASURES:
        if min(value, ci_low, ci_high) <= 0:
            return None
        value, ci_low, ci_high = math.log(value), math.log(ci_low), math.log(ci_high)
    se = (ci_high - ci_low) / (2 * Z95)
    return (value, se) if se > 0 else None


def pool(effects: list[StudyEffect], log_scale: bool = False) -> PooledResult | None:
    if len(effects) < 2:
        return None
    w = [1 / e.se**2 for e in effects]
    fixed = sum(wi * e.estimate for wi, e in zip(w, effects)) / sum(w)
    q = sum(wi * (e.estimate - fixed) ** 2 for wi, e in zip(w, effects))
    df = len(effects) - 1
    c = sum(w) - sum(wi**2 for wi in w) / sum(w)
    tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
    w_star = [1 / (e.se**2 + tau2) for e in effects]
    random = sum(wi * e.estimate for wi, e in zip(w_star, effects)) / sum(w_star)
    se_fixed, se_random = math.sqrt(1 / sum(w)), math.sqrt(1 / sum(w_star))
    i2 = max(0.0, (q - df) / q) * 100 if q > 0 else 0.0
    return PooledResult(
        k=len(effects),
        fixed=fixed,
        fixed_ci=(fixed - Z95 * se_fixed, fixed + Z95 * se_fixed),
        random=random,
        random_ci=(random - Z95 * se_random, random + Z95 * se_random),
        tau2=tau2,
        q=q,
        i2=i2,
        log_scale=log_scale,
    )
