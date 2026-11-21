from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Sample:
    sequence: int
    raw: int


def validate_sample(sequence: int, raw: int, expected_sequence: int) -> None:
    if type(sequence) is not int or sequence != expected_sequence:
        raise ValueError(f'expected sample sequence {expected_sequence}')
    if type(raw) is not int:
        raise ValueError('raw sample must be an integer')


class SampleBuffer:
    def __init__(self) -> None:
        self._samples: list[Sample] = []

    def append(self, sequence: int, raw: int) -> Sample:
        validate_sample(sequence, raw, len(self._samples) + 1)
        sample = Sample(sequence, raw)
        self._samples.append(sample)
        return sample

    def snapshot(self) -> tuple[Sample, ...]:
        return tuple(self._samples)
