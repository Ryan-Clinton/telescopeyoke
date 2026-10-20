# Telling the house when the sky turns

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

`./alert.py watch` changes a Philips Hue light's colour and speaks on a
Google Home or Chromecast speaker when cloud or rain arrives, and again when
the sky clears. It is for the person indoors while the laptop is out with
the telescope.

| What happened | Light | Speaker says |
|---|---|---|
| The run's stars have dimmed to 60% of their best | Orange | "Getting cloudy." |
| They have fallen to 20% | Red | "Clouded out. The telescope has lost the stars." |
| Rain is likely in the next hour | Blue | "Rain is on the way. Cover the telescope." |
| The stars have been back to 85% for five looks running, after cloud | Green | "The sky has cleared." |

Each is told once, when it changes. The light breathes in its colour for 20
seconds and is then put back as it was, unless somebody changed it
meanwhile, in which case it is left alone.

## What it goes by

- **An imaging run that is going**: the light of the stars measured in each
  frame, the last five set against the best the run has shown. This is real cloud, as the
  telescope sees it, and it is what "cloudy" and "cleared" mean.
- **The forecast** (Open-Meteo, the planner's): rain when the chance in this
  hour or the next is 50% or more. With no run going it may also say cloud
  is coming, when this hour is clear and the next is not. It never says the
  sky has cleared: only stars say that.

## Setting it up

The light needs nothing installed. Press the round button on the Hue bridge,
then within half a minute:

    ./alert.py pair
    ./alert.py lights

The speaker needs two packages, and then shows what it can find:

    sudo apt install python3-pychromecast python3-gtts
    ./alert.py speakers

Then name the two in `config.toml`:

    [alerts]
    light = "Living room lamp"
    speaker = "Kitchen speaker"

and try it:

    ./alert.py test cloud
    ./alert.py say "Hello from the telescope"

Other settings under `[alerts]`, all optional: `seconds` (20), `brightness`
(100), `restore` (true), `every` (60, the seconds between looks), `volume`
(0 to 1; left alone if not given), `speaker_address` (worth giving if the
speaker is not found by name), and a colour or sentence for any event, as
`cloud_colour = "Purple"` or `rain_words = "Get the washing in."`. Colours:
Green, Red, Orange, Yellow, Blue, Purple, Pink, Cyan.

## What to know

- The bridge's key is kept in `cache/hue.json`, which git ignores. Everything
  said to the bridge stays on your network.
- The speech is made by gTTS, which uses an unofficial Google service and
  can stop working without notice. A sentence is rendered once and kept, so
  one that has been said before needs no internet. A speaker that fails
  never stops the light.
- The speaker fetches the sound from this computer: one file, at an address
  nobody could guess, for the seconds it takes to play.
- `--dry-run` on any command says what would be done and touches nothing.
- Proven on the real light and speaker: cloud and rain alerts changed a Hue
  light and spoke on a Google speaker, and the call at 04:59 on 20 October
  pulsed the house's lights, spoke and sent the phone message
  (`docs/validation.md`).

## Calling the person

`./alert.py call "words"` gets the person's attention when the telescope
needs their hands or eyes: every light on the bridge pulses (red where it
can), the speaker says the words, and they go to the phone by Telegram.
Every light, not only the one chosen for the sky, so it is used only when
the person has said so for that night (19 October 2026: alone in the
house, they asked for it).
