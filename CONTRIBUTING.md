# Contributing

Thanks for looking. This is a small project and means to stay one: one
person should be able to read it and understand how the whole telescope
works.

## The most useful thing: a hardware report

If you try telescopeyoke on your own mount or camera, say what happened,
working or not. That is how the table of what has been tried, in the README,
grows; your GitHub name goes beside your row if you want it there.

1. Run `./doctor.py --report` (or press "Write a hardware report" on the
   application's Doctor screen). It writes out what the computer is, what the
   handset says the mount is, and every check. It leaves out your location
   and moves nothing.
2. Paste it into a "Hardware compatibility report" issue and tick what you
   tried.

A report from someone who only ran the doctor, and moved nothing, is still
worth having. A question such as "will it work with my HEQ5?" does not need
an issue: ask in
[Discussions](https://github.com/Ryan-Clinton/telescopeyoke/discussions).

## Running it without hardware

```bash
./install.sh --demo           # the libraries, then TelescopeYoke (demo) in its window
./tonight.py --demo
./mount.py --demo goto M27
pytest
```

`./doctor.py` shows what is installed and connected.

## Code

- **Run `pytest` before sending a pull request.** The tests need no hardware
  and take about three minutes. CI runs them on Python 3.11 to 3.14.
- **Anything that changes how the mount moves needs a test against
  `simulator.py`.** If the simulator cannot express what you need, extend it
  in the same pull request.
- **Keep `--demo` working.** New features should run, or decline politely,
  with no telescope attached.
- **Match the surrounding code.** Plain functions, short modules, comments
  that say why. No new dependencies without a good reason.
- **Hardware details go in `config.toml`,** with a default in `config.py`
  that keeps the original setup working.
- **Say what you tested on.** A change proven on real equipment and one only
  run against the simulator are both welcome; the README's status section
  should stay true about which is which.

## Safety

The mount is real machinery and the software cannot see it. Do not add
anything that moves it without a person having asked for that move, and do
not add controls to the status page (`serve.py`): it is served to the local
network without a login. Controls belong in the console (`console.py`),
which answers this computer only; a new control there is one more row in its
table of fixed commands, with a test, and anything that moves the mount goes
through the plan a person confirms.

## What is out of scope

ASCOM, mobile apps, plugin systems, cloud services, a sequencing language,
large front-end frameworks. NINA and KStars/Ekos do those well.
