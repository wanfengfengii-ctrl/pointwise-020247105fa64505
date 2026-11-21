from fractions import Fraction

from rules.values import parse_rational


def require_label(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')
    return value


def validate_rule_parameters(
    rule_id: str,
    revision_id: str,
    scale: int | Fraction | str,
    threshold: int | Fraction | str,
) -> tuple[str, str, Fraction, Fraction]:
    require_label(rule_id, 'rule id')
    require_label(revision_id, 'revision id')
    coefficient = parse_rational(scale)
    limit = parse_rational(threshold)
    if coefficient <= 0:
        raise ValueError('scale must be positive')
    if limit < 0:
        raise ValueError('threshold must be nonnegative')
    return rule_id, revision_id, coefficient, limit
