"""Run this project's full unittest suite and joint live checks from the repo root."""
import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()

    # Joint device/station verification: stopped-path interleave plus the live
    # discard-vs-archive adjudication, real commit denial and reopen continuation.
    joint_ok = False
    if successful:
        try:
            from live_fixture import check_fixture, check_live_fixture
            check_fixture()
            check_live_fixture()
            joint_ok = True
        except Exception as exc:  # noqa: BLE001 - verification must report any failure
            print(f'JOINT CHECK FAILED {type(exc).__name__}: {exc}', file=sys.stderr)
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'joint_live_checks={"PASS" if joint_ok else "FAIL"} '
          f'result={"PASS" if successful and joint_ok else "FAIL"}')
    return 0 if successful and joint_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
