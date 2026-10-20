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
        default = ("OK " + str(int(order[2:])) if order.startswith(":M") else
                   "OK S" + order[2:] if order.startswith(":S") else "NO")
        answer = self.replies.get(order, default)
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


def test_a_speed_is_set_before_moves_and_the_wait_follows_it():
    """19 October 2026: trying step speeds on the telescope, without loading
    the firmware again for each."""
    nano = Nano()
    motor = focuser.Focuser(nano)
    motor.speed(40)
    motor.move(100)
    assert nano.sent == [":S40", ":M+100"] and motor.step_seconds == 0.04
    with pytest.raises(ValueError):
        motor.speed(1)


def test_an_old_firmware_that_does_not_know_speeds_is_an_error():
    motor = focuser.Focuser(Nano({":S40": "NO"}))
    with pytest.raises(RuntimeError):
        motor.speed(40)


def test_the_firmware_takes_speeds_within_the_same_limits():
    sketch = (focuser.SKETCH / "focuser.ino").read_text()
    assert "if (ms < 2 || ms > 200)" in sketch and "delay(stepMs);" in sketch


def protractor(path, angle, width=1280, height=720, shift=(0, 0), scale=1.0, seed=0, off=(0, 0)):
    """A picture like the phone's: a white protractor with blue spokes on a
    dark bracket, a dark hub, and a blacked stick across its middle at `angle` degrees
    (y down), moved and zoomed as a phone switching lens moves it."""
    import numpy as np
    from PIL import Image, ImageDraw
    rng = np.random.default_rng(seed)
    k = 4      # drawn four times over and shrunk: Pillow's thick lines have ragged ends
    img = Image.new("RGB", (width * k, height * k), (40, 40, 45))
    d = ImageDraw.Draw(img)
    cx, cy, r = k * (width / 2 + shift[0]), k * (height / 2 + shift[1]), k * 180 * scale
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(235, 235, 232))
    for a in range(0, 360, 10):
        t = np.radians(a)
        d.line([cx + 0.6 * r * np.cos(t), cy + 0.6 * r * np.sin(t), cx + 0.9 * r * np.cos(t),
                cy + 0.9 * r * np.sin(t)], fill=(70, 90, 170), width=2 * k)
    d.ellipse([cx - 0.15 * r, cy - 0.15 * r, cx + 0.15 * r, cy + 0.15 * r], fill=(60, 60, 65))
    t = np.radians(angle)
    sx, sy = cx + k * off[0], cy + k * off[1]          # the shaft, if the paper is not centred on it
    ends = [sx - 0.3 * r * np.cos(t), sy - 0.3 * r * np.sin(t), sx + 0.8 * r * np.cos(t), sy + 0.8 * r * np.sin(t)]
    d.line(ends, fill=(30, 28, 30), width=int(9 * scale * k))
    img = img.resize((width, height), Image.LANCZOS)
    noisy = np.asarray(img, dtype=np.float32) + rng.normal(0, 4, (height, width, 3))
    Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8)).save(path, quality=90)


def test_the_stick_s_angle_is_read_to_a_fifth_of_a_degree(tmp_path):
    """In one picture, with the stick 0.8 of the protractor's radius long on
    one side: within 0.08° on bare paper, and a printed line lying just
    beside the stick adds about 0.1°."""
    for angle in (3.0, 47.3, 91.0, 178.2):
        protractor(tmp_path / "p.jpg", angle)
        assert focuser.pointer_angle(tmp_path / "p.jpg") == pytest.approx(angle, abs=0.25)


def test_a_phone_switching_lens_does_not_change_the_angle(tmp_path):
    """19 October 2026: between two pictures the Pixel moved and zoomed the
    whole scene by itself."""
    protractor(tmp_path / "a.jpg", 20.0)
    protractor(tmp_path / "b.jpg", 20.0, shift=(-120, 60), scale=1.25, seed=1)
    a, b = focuser.pointer_angle(tmp_path / "a.jpg"), focuser.pointer_angle(tmp_path / "b.jpg")
    assert abs(focuser.turned(a, b)) < 0.1


def test_a_turn_across_the_ends_of_the_scale_is_small():
    assert focuser.turned(179.5, 0.5) == pytest.approx(1.0)
    assert focuser.turned(0.5, 179.5) == pytest.approx(-1.0)
    assert focuser.turned(10.0, 55.0) == pytest.approx(45.0)


def test_no_protractor_no_angle(tmp_path):
    from PIL import Image
    Image.new("RGB", (320, 240), (30, 30, 30)).save(tmp_path / "dark.jpg")
    assert focuser.pointer_angle(tmp_path / "dark.jpg") is None


def test_the_bench_run_finds_the_step_and_the_slack(tmp_path):
    """A motor with 4076 half-steps to a turn (the 28BYJ-48's real gearing,
    not the 4096 on paper) and 40 half-steps of slack, its shaft's stick
    photographed against the protractor."""
    per_step, slack = 360 / 4076, 40

    class Motor:
        commanded = shaft = 0.0

        def move(self, steps):
            self.commanded += steps
            # The shaft follows only once the slack is taken up.
            if self.commanded > self.shaft + slack / 2:
                self.shaft = self.commanded - slack / 2
            elif self.commanded < self.shaft - slack / 2:
                self.shaft = self.commanded + slack / 2

    motor, count = Motor(), [0]

    def picture():
        count[0] += 1
        path = tmp_path / f"{count[0]}.jpg"
        protractor(path, (30 + motor.shaft * per_step) % 180, width=640, height=360, scale=0.9, seed=count[0])
        return path

    said = []
    answer = focuser.bench(motor, picture, looks=2, say=said.append, sleep=lambda s: None)
    assert answer["half_steps_per_turn"] == pytest.approx(4076, rel=0.01)
    for way in ("reversing in", "reversing out"):
        assert answer["slack_half_steps"][way] == pytest.approx(slack, abs=8)
    assert answer["comes_back_within_deg"] < 0.3
    # Half-size pictures here: each reading is good to about 0.3°, so a move
    # (the difference of two) to about 0.6°. Enough to catch 1.4° read for 5.7°.
    assert all(m["measured_deg"] == pytest.approx(m["expected_deg"], abs=0.6) for m in answer["small_moves"])
    assert len(said) == 4 and said[0] == "the camera runs 0 pictures behind the motor"


def test_the_watcher_takes_only_a_picture_made_after_it_was_asked(tmp_path):
    import shutil, threading
    from PIL import Image
    Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / "old.jpg")
    kept = tmp_path / "kept.jpg"
    shutil.copyfile(tmp_path / "old.jpg", kept)
    watcher = focuser.Watcher(kept, tmp_path)
    with pytest.raises(RuntimeError):
        watcher.picture(tmp_path / "a.jpg", wait=0.5)          # nothing new
    threading.Timer(0.3, lambda: Image.new("RGB", (8, 8), (9, 9, 9)).save(kept)).start()
    got = watcher.picture(tmp_path / "b.jpg", wait=3)
    assert Image.open(got).getpixel((0, 0))[0] > 5


def test_a_camera_running_behind_the_motor_is_waited_for(tmp_path):
    """19 October 2026: the phone's stream ran a second or two behind, and
    pictures taken a fixed time after a move caught the stick still turning."""
    per_step = 360 / 4076

    class Motor:
        shaft = 0.0

        def move(self, steps):
            self.shaft += steps

    motor, shown, count = Motor(), [], [0]

    def picture():
        shown.append(motor.shaft)
        lagging = shown[max(0, len(shown) - 4)]          # what the camera saw three pictures ago
        count[0] += 1
        path = tmp_path / f"{count[0]}.jpg"
        protractor(path, (30 + lagging * per_step) % 180, width=640, height=360, scale=0.9, seed=count[0])
        return path

    said = []
    answer = focuser.bench(motor, picture, looks=2, say=said.append, sleep=lambda s: None)
    assert said[0] == "the camera runs 3 pictures behind the motor"
    assert all(m["measured_deg"] == pytest.approx(m["expected_deg"], abs=0.6) for m in answer["small_moves"])
    assert answer["half_steps_per_turn"] == pytest.approx(4076, rel=0.01)


def test_a_stick_off_the_paper_s_middle_is_read_whole(tmp_path):
    """19 October 2026: the protractor is cut out by hand, so the shaft is
    not its middle, and a search only through the middle flipped between
    two wrong lines 12° apart."""
    for angle in (20.0, 70.0, 115.0):
        protractor(tmp_path / "p.jpg", angle, off=(25, -18))
        assert focuser.pointer_angle(tmp_path / "p.jpg") == pytest.approx(angle, abs=0.25)


def test_the_load_test_says_which_way_the_drive_slips(tmp_path):
    """A knob that follows the motor out in full but only a third of the way
    in (the bracket swinging on its thumbscrew), with 40 half-steps of slack:
    the load test reads the knob's stick and names the direction."""
    per_step, slack = focuser.DEGREES_PER_HALF_STEP, 40

    class Drive:
        commanded = knob = 0.0

        def move(self, steps):
            self.commanded += steps
            if self.commanded > self.knob + slack / 2:
                self.knob = self.commanded - slack / 2
            elif self.commanded < self.knob - slack / 2:
                gain = self.knob - (self.commanded + slack / 2)
                self.knob -= gain / 3                        # most of the turn lost going in
                self.commanded = self.knob + slack / 2

    drive, count = Drive(), [0]

    def picture():
        count[0] += 1
        path = tmp_path / f"{count[0]}.jpg"
        protractor(path, (30 + drive.knob * per_step) % 180, width=640, height=360, scale=0.9, seed=count[0])
        return path

    said = []
    answer = focuser.load_test(drive, picture, looks=2, say=said.append, sleep=lambda s: None)
    out, inward = answer["legs"][0], answer["legs"][1]
    assert out["share_through"] == pytest.approx(1.0, abs=0.1) and inward["share_through"] == pytest.approx(0.33, abs=0.1)
    assert answer["verdict"].startswith("it slips in only")
