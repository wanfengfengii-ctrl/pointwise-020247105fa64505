from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from archive.calibrate import CalibratedSample


@dataclass(frozen=True, slots=True)
class PeakResult:
    magnitude: Fraction
    sequence: int
    exceeded: bool


def find_peak(samples: Iterable[CalibratedSample], threshold: Fraction) -> PeakResult:
    iterator = iter(samples)
    first = next(iterator, None)
    if first is None:
        raise ValueError('cannot compute a peak without samples')
    magnitude = abs(first.velocity)
    sequence = first.sequence
    for sample in iterator:
        candidate = abs(sample.velocity)
        if candidate > magnitude:
            magnitude = candidate
            sequence = sample.sequence
    return PeakResult(magnitude, sequence, magnitude > threshold)
