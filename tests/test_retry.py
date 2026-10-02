import logging

import pytest

from src.infrastructure.retry import RetryPolicy, TransientError, retry_call


class Flaky:
    """Callable that raises the given exceptions in turn, then returns 'ok'."""

    def __init__(self, *errors: Exception):
        self.errors = list(errors)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


POLICY = RetryPolicy(max_attempts=4, initial_delay=1, max_delay=5, jitter=0)


def run(func, policy=POLICY, **kwargs):
    sleeps: list[float] = []
    result = retry_call(
        func, policy=policy, description="test op", sleep=sleeps.append, rand=lambda: 0.5, **kwargs
    )
    return result, sleeps


def test_returns_immediately_on_success():
    func = Flaky()
    assert run(func) == ("ok", [])
    assert func.calls == 1


def test_retries_transient_errors_with_exponential_backoff():
    func = Flaky(TransientError("429"), TimeoutError(), ConnectionError())
    result, sleeps = run(func)
    assert result == "ok"
    assert func.calls == 4
    assert sleeps == [1, 2, 4]


def test_backoff_is_capped_at_max_delay():
    policy = RetryPolicy(max_attempts=6, initial_delay=1, max_delay=5, jitter=0)
    func = Flaky(*[TransientError("x") for _ in range(5)])
    _, sleeps = run(func, policy=policy)
    assert sleeps == [1, 2, 4, 5, 5]


def test_permanent_errors_are_not_retried():
    func = Flaky(ValueError("bad request"))
    with pytest.raises(ValueError):
        run(func)
    assert func.calls == 1


def test_gives_up_after_max_attempts_and_reraises_original(caplog):
    error = TransientError("still down")
    func = Flaky(*[error] * 10)
    with caplog.at_level(logging.WARNING), pytest.raises(TransientError) as info:
        run(func)
    assert info.value is error
    assert func.calls == POLICY.max_attempts
    assert "failed after 4 attempt(s)" in caplog.text


def test_logs_each_retry(caplog):
    with caplog.at_level(logging.WARNING):
        run(Flaky(TransientError("rate limited")))
    assert "test op failed (attempt 1/4)" in caplog.text
    assert "rate limited" in caplog.text


def test_honours_retry_after_hint():
    _, sleeps = run(Flaky(TransientError("429", retry_after=20)))
    assert sleeps == [20]


def test_custom_predicate():
    func = Flaky(KeyError("flaky"))
    result, _ = run(func, is_retryable=lambda e: isinstance(e, KeyError))
    assert result == "ok"


def test_keyboard_interrupt_is_never_retried():
    func = Flaky(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        run(func)
    assert func.calls == 1


def test_jitter_stays_within_bounds():
    policy = RetryPolicy(initial_delay=10, max_delay=100, jitter=0.2)
    assert policy.backoff(1, rand=0.0) == pytest.approx(8)
    assert policy.backoff(1, rand=0.999999) == pytest.approx(12, rel=1e-4)


@pytest.mark.parametrize(
    "kwargs",
    [{"max_attempts": 0}, {"initial_delay": 10, "max_delay": 1}, {"jitter": 1.5}],
)
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)
