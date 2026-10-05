# Testing

```bash
pytest -q                         # everything, about three minutes, no hardware
pytest -q tests/test_mount.py     # mount logic against the simulated handset
```

CI runs the suite and the demo commands on Python 3.11 to 3.14, on Linux and
on Windows. Neither has any hardware.

- `tests/test_sky.py`, `test_planner.py`: astronomy, the report, the page, doctor.
- `tests/test_mount.py`, `test_tracking.py`: limits, GoTo, drift model and
  cancelling, on both sides of the mount.
- `tests/test_stacking.py`, `test_imaging.py`: the imaging pipeline on
  made-up star fields with known answers; focusing.
- `tests/test_camera.py`: one contract held by both camera routes, INDI and
  Altair's library, each against a made-up stand-in; and the SDK route's own
  hazards (late frames, time-outs, an unplugged camera, two cameras).
- `tests/test_host.py`: what differs on Windows (`host.py`): COM ports,
  previews held open, speech in order, UTF-8 output through a pipe.
- `tests/test_interface.py`: the JSON envelope against `schemas/`, error
  codes, dry runs, the MCP server, and the scenarios in `evals/`.

Rules: a change to how the mount moves comes with a simulator test; a change
to JSON output keeps the schemas and tests in step; tests never need a
camera, a mount, the network or `config.toml`.

`tests/test_demo.py` runs the real commands in the full demo (pretend mount,
camera and sky) in a scratch folder: a GoTo with centring, the focusing aid,
an imaging run, cloud and a pulled lead.

What the tests cannot cover: the real mount, camera and sky. Say in the
README's status section what has and has not been run for real.
