"""newhardware.py: a new device noticed without sending it anything, asked
what it is only when the person chooses, and the report offered, never sent."""
import io
import urllib.parse

import config
import newhardware
import doctor

FTDI = {"device": "/dev/ttyUSB0", "description": "FT231X USB UART", "maker": "FTDI", "usb": "0403:6015"}
CH340 = {"device": "/dev/ttyUSB1", "description": "USB Serial", "maker": "QinHeng", "usb": "1A86:7523"}
PROLIFIC = {"device": "/dev/ttyUSB2", "description": "USB-Serial Controller", "maker": "Prolific", "usb": "067B:2303"}


def test_a_device_is_new_until_it_is_known_or_in_use(tmp_path, monkeypatch):
    monkeypatch.setattr(newhardware, "KNOWN", tmp_path / "known.json")
    found = newhardware.look([FTDI, CH340, PROLIFIC], known=set(), used={"/dev/ttyUSB0"}, networks=[])
    assert [d["state"] for d in found] == ["in use", "new", "new"]
    newhardware.mark_known("/dev/ttyUSB1", details=[FTDI, CH340, PROLIFIC])
    found = newhardware.look([FTDI, dict(CH340, device="/dev/ttyUSB3"), PROLIFIC], used={"/dev/ttyUSB0"}, networks=[])
    assert [d["state"] for d in found] == ["in use", "known", "new"]    # known by its USB numbers, wherever it lands


def test_the_report_leaves_out_serial_numbers_and_the_form_is_filled_in_not_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(newhardware, "REPORTS", tmp_path / "reports")
    text = ("port /dev/serial/by-id/usb-Prolific_USB-Serial_Controller_A1B2C3D4E5-if00-port0\n"
            "serial number: ZX81ABCDEF\nno SynScan handset answered at 9600 baud\n")
    answer = newhardware.probe("/dev/ttyUSB2", details=[PROLIFIC], reporter=lambda port: text)
    kept = open(answer["report"]).read()
    assert "A1B2C3D4E5" not in kept and "ZX81ABCDEF" not in kept and "no SynScan handset" in kept
    fields = urllib.parse.parse_qs(urllib.parse.urlparse(answer["form"]).query)
    assert fields["template"] == ["mount-support.yml"] and fields["title"] == ["Mount support: USB-Serial Controller"]
    assert "no SynScan handset" in fields["doctor"][0]


def test_watching_says_each_new_device_once(tmp_path, monkeypatch):
    monkeypatch.setattr(newhardware, "NEW", tmp_path / "new.json")
    seen = [[FTDI], [FTDI, PROLIFIC], [FTDI, PROLIFIC]]
    said, sent = [], []
    looks = iter(seen)
    newhardware.watch(say=said.append, every=0, rounds=3, send=lambda text: sent.append(text),
                      looker=lambda: newhardware.look(next(looks), known=set(), used={"/dev/ttyUSB0"}, networks=[]))
    assert len(said) == 1 and "USB-Serial Controller" in said[0] and len(sent) == 1
    assert "--probe PORT" in sent[0] and (tmp_path / "new.json").exists()


class Port(io.BytesIO):
    """A pretend serial port answering LX200's two questions."""
    def __init__(self, answers):
        super().__init__()
        self.answers, self.asked = answers, []

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.asked.append(data)

    def read_until(self, end, size):
        return self.answers.get(self.asked[-1], b"")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_an_lx200_family_mount_says_what_it_is_and_silence_says_nothing():
    am5 = Port({b":GVP#": b"AM5#", b":GVN#": b"1.9.3#"})
    lines = doctor.lx200("/dev/ttyUSB2", opener=lambda: am5)
    assert lines == ["an LX200-family mount answered at 9600 baud: product AM5, firmware 1.9.3 "
                     "(not yet supported: docs/mounts.md)"] and am5.asked == [b":GVP#", b":GVN#"]
    quiet = Port({})
    assert "nothing on this port answered" in doctor.lx200("/dev/ttyUSB2", opener=lambda: quiet)[-1]
    assert config.DATA is not None


def test_a_synscan_wifi_network_is_noticed_from_the_list_alone_and_its_name_scrubbed():
    import types
    listing = "no:HomeWiFi\nyes:SynScan_4C8A\nno:SynScan_4C8A\n"
    nets = newhardware.wifi_networks(run=lambda *a, **k: types.SimpleNamespace(stdout=listing))
    assert nets == [{"device": "wifi", "description": "SynScan Wi-Fi network SynScan_…", "maker": "Sky-Watcher",
                     "usb": "", "joined": True}]
    found = newhardware.look([], known=set(), used=set(), networks=nets)
    assert found[0]["state"] == "new"


def test_the_wifi_adapter_is_asked_only_what_it_is(monkeypatch):
    monkeypatch.setattr(doctor, "hardware_report", lambda *a: "the doctor's report")
    seen = {"model": "EQ3", "firmware": "3.39.07", "counts_per_turn": 3628800, "moving": [False, False]}
    text = newhardware.wifi_report(finder=lambda: ["192.168.4.1"], describer=lambda address: seen)
    assert "a motor board answered over Wi-Fi" in text and "model EQ3" in text and "not moving" in text
    assert "none answered" in newhardware.wifi_report(finder=lambda: [], describer=None)


def test_the_watch_can_run_from_boot(tmp_path):
    ran = []
    answer = newhardware.install(say=lambda *_: None, run=lambda cmd, check: ran.append(cmd), home=tmp_path)
    unit = (tmp_path / ".config" / "systemd" / "user" / "ty-newhardware.service").read_text()
    assert "newhardware.py --watch" in unit and ran[-1][-1] == "ty-newhardware.service" and answer["installed"]
