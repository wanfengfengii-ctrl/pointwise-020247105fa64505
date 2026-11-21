from dataclasses import dataclass
from fractions import Fraction

from rules.revisions import RuleRevision


@dataclass(frozen=True, slots=True)
class FrozenRule:
    rule_id: str
    revision_id: str
    scale: Fraction
    threshold: Fraction


def freeze_revision(revision: RuleRevision) -> FrozenRule:
    return FrozenRule(
        revision.rule_id,
        revision.revision_id,
        revision.scale,
        revision.threshold,
    )
