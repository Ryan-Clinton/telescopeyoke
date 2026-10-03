"""Minimal INDI client: read and set device properties and receive images.

The stock indi_setprop tool splits on dots, so it cannot address a device
called "Altair ALTAIRH183C(USB2.0)"; this speaks the XML protocol directly.
"""
import base64
import socket
import time
from xml.etree.ElementTree import XMLPullParser
from xml.sax.saxutils import quoteattr

KINDS = {"Switch": "oneSwitch", "Number": "oneNumber", "Text": "oneText"}


class IndiError(Exception):
    pass


class Indi:
    def __init__(self, host="localhost", port=7624):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.parser = XMLPullParser(["start", "end"])
        self.parser.feed("<stream>")
        self.depth = 0
        # (device, property) -> {"kind", "state", "items": {element: value}}
        self.props = {}
        self.blobs = []     # (device, format, bytes), oldest first
        self.messages = []  # driver log lines
        self._send('<getProperties version="1.7"/>')
        self.pump(2)

    def close(self):
        self.sock.close()

    def _send(self, xml):
        self.sock.sendall(xml.encode())

    def pump(self, seconds):
        """Read from the server for up to `seconds`."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            self.sock.settimeout(left)
            try:
                data = self.sock.recv(1 << 20)
            except socket.timeout:
                return
            if not data:
                raise IndiError("INDI server closed the connection")
            self.parser.feed(data)
            for event, el in self.parser.read_events():
                self.depth += 1 if event == "start" else -1
                # Depth 1 is a complete top-level message inside <stream>.
                if event == "end" and self.depth == 1:
                    self._handle(el)
                    el.clear()

    def _handle(self, el):
        tag, device, name = el.tag, el.get("device"), el.get("name")
        if el.get("message"):
            self.messages.append(el.get("message"))
        if tag == "delProperty":
            self.props.pop((device, name), None)
        elif tag == "setBLOBVector":
            for one in el:
                self.blobs.append((device, one.get("format"),
                                   base64.b64decode(one.text or "")))
        elif tag.startswith(("def", "set")) and tag.endswith("Vector"):
            prop = self.props.setdefault((device, name), {"items": {}})
            prop["kind"] = tag[3:-6]
            prop["state"] = el.get("state", prop.get("state"))
            for one in el:
                prop["items"][one.get("name")] = (one.text or "").strip()

    # --- reading ------------------------------------------------------------

    def devices(self):
        return sorted({device for device, _ in self.props})

    def get(self, device, name, element=None):
        prop = self.props.get((device, name))
        if prop is None:
            return None
        return prop["items"] if element is None else prop["items"].get(element)

    def wait(self, test, timeout, what="condition"):
        """Pump until test() is truthy and return its value."""
        end = time.monotonic() + timeout
        while not (value := test()):
            if time.monotonic() > end:
                raise IndiError(f"timed out waiting for {what}")
            self.pump(0.2)
        return value

    def wait_for(self, device, name, timeout=10):
        return self.wait(lambda: self.props.get((device, name)), timeout,
                         f"{device}.{name}")

    # --- writing ------------------------------------------------------------

    def set(self, device, name, **items):
        """Set elements of a property, e.g. set(cam, "CONNECTION", CONNECT="On")."""
        prop = self.wait_for(device, name)
        kind = prop["kind"]
        body = "".join(f"<{KINDS[kind]} name={quoteattr(k)}>{v}</{KINDS[kind]}>"
                       for k, v in items.items())
        self._send(f"<new{kind}Vector device={quoteattr(device)} "
                   f"name={quoteattr(name)}>{body}</new{kind}Vector>")
        self.pump(0.3)

    def connect(self, device, timeout=20):
        if self.get(device, "CONNECTION", "CONNECT") != "On":
            self.set(device, "CONNECTION", CONNECT="On")
            self.wait(lambda: self.get(device, "CONNECTION", "CONNECT") == "On",
                      timeout, f"{device} to connect")
            self.pump(2)  # let the driver publish its full property list

    def expose(self, device, seconds, timeout=None, attempts=3):
        """Take one exposure and return (format, image bytes)."""
        self._send(f"<enableBLOB device={quoteattr(device)}>Also</enableBLOB>")
        for attempt in range(attempts):
            self.blobs.clear()
            self.set(device, "CCD_EXPOSURE", CCD_EXPOSURE_VALUE=seconds)
            try:
                self.wait(lambda: self.blobs, timeout or seconds + 15, "the image")
            except IndiError:
                # The driver sometimes sticks on the first exposure after a
                # settings change or an interrupted client; abort and retry.
                if attempt == attempts - 1:
                    raise
                self.set(device, "CCD_ABORT_EXPOSURE", ABORT="On")
                self.pump(1)
                continue
            _, fmt, data = self.blobs.pop(0)
            return fmt, data
