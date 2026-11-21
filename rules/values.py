from fractions import Fraction


def parse_rational(value: int | Fraction | str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, Fraction, str)):
        raise ValueError('expected an integer, Fraction or exact rational text')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('invalid rational value') from exc
