# Claiming a find: the agent fills the form, the person presses send

When a find is real, the first report wins: the Transient Name Server
credits whoever reports first. So everything up to the send is done for
the person, fast; the send itself is theirs, every time. A report goes out
under their name, public at once, and stays on the record even if it is
withdrawn.

What happens before anyone asks:

1. The patrol (or the search started after any stack, `patrol.py
   --analyse`) vets every candidate. For each one nothing explains, it
   makes the report packet (`report.py ID`: `reports/ID/report.json`,
   `report.txt`, `finding.png`) and sends the person a Telegram alert
   (`notify.py`) with the night, the reference and the difference side by
   side.
2. If the person started the run, the patrol takes 10 more minutes of the
   same field at once (no GoTo) and searches them: a real object is there
   again, and the second alert says "seen on 2 of 2 nights".

## "claim ID": a nova or other transient, to the Transient Name Server

1. Make the packet fresh: `./report.py ID`. Read `reports/ID/report.json`
   and check its "Before sending" list: anything still wanting (one night
   only, one half of the night only, no last non-detection) is said to the
   person first, plainly, before the form is opened.
2. In the browser (Claude in Chrome), search the Server for the place:
   `https://www.wis-tns.org/search?ra=RA&decl=DEC&radius=10&coords_unit=arcsec`
   with the packet's degrees. If something is there, stop and say so: it
   is not new, and the person decides whether a second report helps.
3. The person must be logged in to the Server themselves; never type
   their password. Open the AT report form from the Server's menu (Submit,
   then AT report) and fill it from `report.json`, one field at a time:
   - RA and Dec (`ra`, `dec` in degrees, or `ra_hms`, `dec_dms`);
   - discovery date (`discovered_utc`, UT);
   - discovery magnitude and error (`mag`, `mag_error`), filter "Clear"
     (unfiltered), with the remark that it is calibrated approximately to
     Gaia G;
   - the limiting magnitude of that night (`limit_5sigma`);
   - the last non-detection, date and limit (`last_non_detection`), if
     there is one;
   - instrument and telescope as in `report.txt`;
   - reporter: the person's name as they gave it on the Server;
   - remarks: the checks (`checks`) in one line, and the nights seen.
4. Attach `finding.png` if the form takes a file.
5. Stop. Do not press submit. Tell the person "filled in, everything
   checked, press Submit when you are happy", and say which fields you
   were unsure of.
6. When they have sent it, note the AT name the Server gives in the
   candidate book (`candidates.py`) and in the session's notes.

## What never happens

- Nothing goes to the Transient Name Server from the software or an agent:
  the person presses send there.
- No account is made for the person, and no password is typed.
- A candidate the checks have not cleared is not filled in without saying
  so first.
