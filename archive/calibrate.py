from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from record.seal import SealedOriginal


@dataclass(frozen=True, slots=True)
class CalibratedSample:
    sequence: int
    velocity: Fraction


def calibrate(original: SealedOriginal) -> Iterator[CalibratedSample]:
    for sample in original.samples:
        yield CalibratedSample(sample.sequence, sample.raw * original.rule.scale)
