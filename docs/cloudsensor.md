# The cloud sensor

[Back to the README](../README.md)

A plan, not yet built. A box on the house's wall or roof that looks
straight up all the time and says whether the sky above the garden is
clear, cloudy or raining, without the telescope set up. The same idea as
the Lunatico AAG CloudWatcher (about £400), for about £40 in parts and a
printed case.

The project already has two ways of judging cloud: `clouds.py`, the
Meteosat picture (10 minutes old, kilometres across), and `skywatch.py`,
the camera through the telescope (only once the telescope is set up, and
only where it points). The sensor is the third: this sky, now, all night,
every night.

## How it tells cloud

An infrared thermometer pointed at the zenith reads the sky's temperature.
A clear sky is very cold, often 25 to 40 °C below the air, because it is
looking out into space through dry air. Cloud is warm water close above,
so the reading climbs towards the air's temperature. The gap between the
two is the measurement:

    gap = sky temperature (corrected) - air temperature

A large negative gap is clear, near zero is overcast. Thin cloud and
haze fall in between, which is where the camera still matters.

The raw sky reading also depends on the air's own temperature and
moisture, so it is corrected first, with the formula the Boltwood and AAG
sensors use (INDI's `indi_aagcloudwatcher_ng` driver has it too):

    T = air temperature in °C
    expected = (K1/100)(T - K2/10) + (K3/100) * exp(K4 * T / 1000) ^ (K5/100)
    corrected sky = sky - expected

with K1 = 33, K2 = 0, K3 = 4, K4 = 100, K5 = 100 to start. The thresholds
are not known in advance. They are set from nights when the person in the
garden says what the sky is like, compared with the readings at those
times (`docs/agents/setup-routine.md` step 2 already asks).

## Parts

Prices are rough, from the usual UK sellers in October 2026.

| Part | Job | About |
|---|---|---|
| ESP32 development board (ESP32-WROOM, USB-C) | Reads the sensors, serves the readings over WiFi | £6 |
| MLX90614ESF-BAA | Sky temperature: infrared, 90° view, 3.3 V | £12 |
| BME280 | Air temperature, humidity and pressure, so the dew point | £5 |
| TSL2591 | Daylight and twilight; with care, roughly how dark the sky is | £6 |
| Rain plate: a small PCB with interleaved copper fingers, on an ESP32 touch pin | Rain and dew on the box | £3 |
| Two 47 Ω 1 W resistors and a logic-level MOSFET (AO3400 or IRLZ44N) | Heaters for the rain plate and the sensor's hood, to dry them | £3 |
| IP65 junction box, about 100 × 100 × 70 mm, with two cable glands | The weatherproof case | £8 |
| Outdoor 5 V supply, 1 A or more, or a PoE splitter giving 5 V | Power; the ESP32's WiFi needs a steady 500 mA | £8 |
| Printed hood and bracket in PETG or ASA | Keeps rain and stray light off the sensor | filament |
| Conformal coating spray | Damp protection for the boards | £5 |

**No glass, acrylic or plastic over the MLX90614.** They are opaque at the
8 to 14 µm it reads, so a window makes it measure the window. Its face is
open to the sky at the bottom of a short printed hood that keeps rain off.
A germanium window is the only real alternative and costs more than the
rest together.

**PETG or ASA, not PLA,** for anything outside: PLA softens in summer sun
and goes brittle in UV within a season.

## Wiring

All three sensors share the ESP32's I²C pins, 3.3 V and ground:

| ESP32 pin | Goes to |
|---|---|
| 3V3 | VIN or VCC of the MLX90614, BME280 and TSL2591 |
| GND | GND of all three, the MOSFET's source |
| GPIO 21 (SDA) | SDA of all three |
| GPIO 22 (SCL) | SCL of all three |
| GPIO 4 (touch T0) | The rain plate's fingers, by a short wire |
| GPIO 25 | The MOSFET's gate, through 100 Ω, with 10 kΩ to ground |
| 5V | One end of each heater resistor; the other ends to the MOSFET's drain |

Their I²C addresses differ (MLX90614 0x5A, BME280 0x76 or 0x77, TSL2591
0x29), so they share the bus without changes. The heater resistors are
glued under the rain plate and inside the hood, and draw about 1 W
together. They come on when the rain plate reads wet, or when the air is
within 2 °C of its dew point.

## Where it goes

It needs a clear view straight up and nothing warm underneath it:

- away from the chimney, the boiler's flue and any vents, because warm air
  rising past the sensor reads as cloud;
- a wall bracket above the gutter, or a short pole on the shed, is as good
  as the ridge and needs no ladder on the roof;
- in WiFi range of the router, or with a cable run for PoE;
- the cable glands facing down.

## The software

**On the ESP32**, `firmware/cloudsensor/`, as the focuser's firmware is in
`firmware/focuser/`: it reads every sensor every 10 seconds, runs the
heater, and answers `http://cloudsensor.local/sky` with one JSON reading:

```json
{"sensor": "TY cloudsensor 1", "sky_c": -18.4, "air_c": 6.1,
 "humidity": 81, "dew_point_c": 3.0, "lux": 0.002, "wet": false,
 "heater": false, "uptime_s": 40213}
```

The name in `sensor` is checked the way the focuser's "TY focuser 1" is,
so nothing else on the network is mistaken for it.

**On the laptop**, `cloudsensor.py`:

    ./cloudsensor.py               the reading now: clear, cloudy, overcast or rain, and the numbers
    ./cloudsensor.py --json        the same as JSON, with its schema in schemas/
    ./cloudsensor.py --log         keep a reading every minute in config.DATA/cache/sky.jsonl
    ./cloudsensor.py --night       tonight's readings as a strip: when it was clear

The address is one row in `config.SETTINGS`, so the Settings screen can
change it. The thresholds start from the figures above and are refined
from the log.

**What uses it:**

- `tonight.py` and the console say "clear here now" or "cloudy here now"
  beside the forecast, and the log shows how often the forecast was wrong
  in each direction;
- `shoot.py --through-cloud` pauses on the sensor's word as well as the
  frames', and starts again when the sky has stayed clear for a few
  minutes, with no frames lost while it waits;
- rain makes `shoot.py` stop and say so at once: the telescope is out in
  it;
- an alert when a gap opens, only if asked for: the light alerts are off.

## Order of work

1. On the bench, by USB: the ESP32 with the three sensors, printing
   readings. Point it out of a window, then outside on a clear night and a
   cloudy one, to see the gap change.
2. WiFi and the `/sky` answer; `cloudsensor.py` reading it, with tests
   against a pretend sensor, as `focuser.py`'s tests use a pretend Nano.
3. The heater and the rain plate.
4. The box, the hood and the bracket; up on the wall.
5. A fortnight of `--log` beside what the person in the garden says, to set
   the thresholds.
6. `tonight.py`, the console and `shoot.py` using it.

Nothing here has been built or tried yet.
