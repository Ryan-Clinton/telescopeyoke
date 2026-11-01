import os
import subprocess

import pytest

import usbpower


def plug(root, place, vendor="16d0"):
    d = root / place
    d.mkdir(parents=True, exist_ok=True)
    (d / "idVendor").write_text(vendor + "\n")
    return d


def hub(root, name, ports=4, peer=None):
    """A hub's sysfs folder with its port folders; peer links each port to
    the same port on the hub's other half, as the kernel does."""
    d = plug(root, name, "0bda")
    for n in range(1, ports + 1):
        p = d / f"{name}:1.0" / f"{name}-port{n}"
        p.mkdir(parents=True)
        if peer:
            other = root / peer / f"{peer}:1.0" / f"{peer}-port{n}"
            other.mkdir(parents=True, exist_ok=True)
            os.symlink(other, p / "peer")
    return d


class Hub:
    """uhubctl in a fake: the camera leaves USB when its port is off and is
    back a second after it is on."""
    def __init__(self, root, place, fail=None):
        self.root, self.place, self.fail, self.calls, self.t = root, place, fail, [], 0.0
        self.on_at = None

    def run(self, command, **_):
        args = command[command.index("uhubctl"):]
        self.calls.append(args)
        action = args[args.index("-a") + 1]
        if self.fail == action:
            return subprocess.CompletedProcess(command, 1, "", "No compatible devices detected!\n")
        if action == "off":
            for f in (self.root / self.place).glob("idVendor"):
                f.unlink()
        else:
            self.on_at = self.t
        return subprocess.CompletedProcess(command, 0, "", "")

    def sleep(self, s):
        self.t += s
        if self.on_at is not None and self.t - self.on_at >= 1.0:
            plug(self.root, self.place)

    def clock(self):
        return self.t


@pytest.fixture
def usb(tmp_path):
    root = tmp_path / "usb"
    hub(root, "1-5")
    hub(root, "2-5", peer="1-5")
    (root / "1-5" / "speed").write_text("480\n")
    (root / "2-5" / "speed").write_text("5000\n")
    plug(root, "2-5.1")
    return root


def test_cuts_both_halves_of_the_port_and_waits_for_the_camera(usb, tmp_path):
    fake = Hub(usb, "2-5.1")
    said = []
    found = usbpower.cycle(off=8, root=usb, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                           memory=tmp_path / "port.json", say=said.append)
    assert [c[1:] for c in fake.calls] == [
        ["-l", "2-5", "-p", "1", "-a", "off"], ["-l", "1-5", "-p", "1", "-a", "off"],
        ["-l", "2-5", "-p", "1", "-a", "on"], ["-l", "1-5", "-p", "1", "-a", "on"]]
    assert found["back"] and found["ports"] == ["2-5.1", "1-5.1"] and found["off_s"] == 8
    assert 0 < found["back_after_s"] <= 1.5
    assert usbpower.remembered(tmp_path / "port.json") == "2-5.1"


def test_a_camera_gone_from_usb_is_cycled_at_its_last_place(usb, tmp_path):
    usbpower.remember("2-5.1", tmp_path / "port.json")
    (usb / "2-5.1" / "idVendor").unlink()            # jammed and dropped off USB
    fake = Hub(usb, "2-5.1")
    found = usbpower.cycle(root=usb, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                           memory=tmp_path / "port.json", say=lambda _: None)
    assert found["back"] and found["place"] == "2-5.1"


def test_power_is_given_back_even_when_turning_it_off_fails(usb, tmp_path):
    fake = Hub(usb, "2-5.1", fail="off")
    with pytest.raises(usbpower.PowerError, match="No compatible devices"):
        usbpower.cycle(root=usb, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                       memory=tmp_path / "port.json", say=lambda _: None)
    assert fake.calls[-1][-1] == "on"


def test_a_camera_that_stays_away_is_reported_not_raised(usb, tmp_path):
    fake = Hub(usb, "2-5.1")
    fake.sleep = lambda s: setattr(fake, "t", fake.t + s)        # never comes back
    found = usbpower.cycle(back=5, root=usb, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                           memory=tmp_path / "port.json", say=lambda _: None)
    assert found["back"] is False


def test_no_hub_port_to_switch(tmp_path):
    root = tmp_path / "usb"
    plug(root, "2-1")                                  # straight into the laptop
    with pytest.raises(usbpower.PowerError, match="laptop's own port"):
        usbpower.cycle(root=root, run=None, memory=tmp_path / "port.json", say=lambda _: None)


def test_never_seen_and_not_plugged_in(tmp_path):
    with pytest.raises(usbpower.PowerError, match="press the hub's port button"):
        usbpower.cycle(root=tmp_path / "none", run=None, memory=tmp_path / "port.json", say=lambda _: None)


def test_dry_run_switches_nothing(capsys):
    import camera_test
    import sys
    argv = sys.argv
    sys.argv = ["camera_test.py", "--power-cycle", "--dry-run"]
    try:
        camera_test.main()
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    assert "Cuts the camera's power at the hub" in capsys.readouterr().out


def test_found_on_the_usb2_half_it_comes_back_on_usb3(tmp_path):
    """1 November 2026: with the USB 2 half switched on first, the camera came
    back at 480 Mb/s. The USB 3 half is always switched on first."""
    root = tmp_path / "usb"
    hub(root, "4-2")
    hub(root, "3-2", peer="4-2")
    (root / "3-2" / "speed").write_text("480\n")
    (root / "4-2" / "speed").write_text("5000\n")
    plug(root, "3-2.1")
    fake = Hub(root, "3-2.1")
    usbpower.cycle(root=root, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                   memory=tmp_path / "port.json", say=lambda _: None)
    ons = [c[2] for c in fake.calls if c[-1] == "on"]
    assert ons == ["4-2", "3-2"]
