"""The focuser's motor: what focuser.py sends the Nano and what it accepts back."""
import pytest

import focuser


class Nano:
    """Answers as firmware/focuser does, a byte at a time."""

    def __init__(self, replies=None):
        self.sent, self.waiting, self.replies = [], b"", replies or {}

    def write(self, data):
        order = data.decode().strip()
        self.sent.append(order)
        answer = self.replies.get(order, "OK " + str(int(order[2:])) if order.startswith(":M") else "NO")
        self.waiting += answer.encode() + b"\r\n"

    def read(self, count):
        out, self.waiting = self.waiting[:count], self.waiting[count:]
        return out


def test_a_move_is_one_signed_order_and_waits_for_its_answer():
    nano = Nano()
    motor = focuser.Focuser(nano)
    motor.move(1024)
    motor.move(-1024)
    assert nano.sent == [":M+1024", ":M-1024"]


def test_a_move_the_nano_refuses_is_an_error():
    motor = focuser.Focuser(Nano({":M+5": "NO"}))
    with pytest.raises(RuntimeError, match="NO"):
        motor.move(5)


def test_nothing_is_sent_for_no_move_or_too_long_a_one():
    nano = Nano()
    for steps in (0, focuser.MOST + 1, -focuser.MOST - 1):
        with pytest.raises(ValueError):
            focuser.Focuser(nano).move(steps)
    assert nano.sent == []


def test_the_firmware_and_the_script_agree_on_the_longest_move():
    sketch = (focuser.SKETCH / "focuser.ino").read_text()
    assert f"const long MOST = {focuser.MOST};" in sketch


def test_the_script_waits_as_long_as_the_firmware_takes_over_a_step():
    sketch = (focuser.SKETCH / "focuser.ino").read_text()
    assert f"const int STEP_MS = {round(focuser.STEP_SECONDS * 1000)};" in sketch
