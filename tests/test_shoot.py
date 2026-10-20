"""shoot.py on its own: what a session records about itself."""
import shoot


def test_a_session_records_whether_the_clock_was_kept_to_time():
    import types
    assert shoot.clock_state(lambda *a, **k: types.SimpleNamespace(stdout="yes\n"))["synchronized"] is True
    assert shoot.clock_state(lambda *a, **k: types.SimpleNamespace(stdout="no\n"))["synchronized"] is False

    def missing(*a, **k):
        raise FileNotFoundError("timedatectl")
    assert shoot.clock_state(missing)["synchronized"] == "unknown"
