from dataclasses import dataclass
from fractions import Fraction

from rules.validate import require_label


@dataclass(frozen=True, slots=True)
class RuleRevision:
    rule_id: str
    revision_id: str
    scale: Fraction
    threshold: Fraction


class RevisionRegistry:
    def __init__(self) -> None:
        self._revisions: dict[tuple[str, str], RuleRevision] = {}

    def get(self, rule_id: str, revision_id: str) -> RuleRevision:
        require_label(rule_id, 'rule id')
        require_label(revision_id, 'revision id')
        return self._revisions[rule_id, revision_id]

    def remember(self, revision: RuleRevision) -> RuleRevision:
        key = (revision.rule_id, revision.revision_id)
        existing = self._revisions.get(key)
        if existing is not None:
            if existing != revision:
                raise ValueError(f'conflicting rule revision {key!r}')
            return existing
        self._revisions[key] = revision
        return revision
