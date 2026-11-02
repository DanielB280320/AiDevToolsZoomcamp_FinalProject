"""Demo-only build-time fault for scenario S1, "bad release" (spec §15.3, D91). OFF in real builds.

`S1_FINISH_RAISES` is a constant in the source, not a flag or an env var, because S1 is about a
release: the broken build must be a different image than the good one, so that rolling back to
`PREVIOUS_TAG` removes the fault. The drill flips it in one small PR (`scripts/demo-s1-enable.sh`),
which CI builds, dev deploys and "Promote to production" ships; the fix is a revert of that PR
(`test_shipped_build_has_no_demo_fault` is the guard). Nothing else may read or set it: it must not
become a runtime switch (that would make S1 a flag scenario like S2 and S3).

The fault is a route dependency on `POST /sessions/{id}/finish`. It runs before authentication, so
the drill's traffic needs no account and no health data. It carries no message, so logs and traces
see only the class name (`DemoFaultError`), like any other unhandled error.
"""

# Deliberately not `Final`: the unit tests flip it for the duration of one test.
S1_FINISH_RAISES: bool = False


class DemoFaultError(RuntimeError):
    """Raised by the S1 demo build on `finish`; never raised while `S1_FINISH_RAISES` is False."""


def finish_session_fault() -> None:
    if S1_FINISH_RAISES:
        raise DemoFaultError
