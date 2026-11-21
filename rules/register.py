from fractions import Fraction

from rules.revisions import RevisionRegistry, RuleRevision
from rules.validate import validate_rule_parameters


def register(
    registry: RevisionRegistry,
    rule_id: str,
    revision_id: str,
    scale: int | Fraction | str,
    threshold: int | Fraction | str,
) -> RuleRevision:
    parameters = validate_rule_parameters(rule_id, revision_id, scale, threshold)
    return registry.remember(RuleRevision(*parameters))
