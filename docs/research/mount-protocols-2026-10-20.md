# Mount control protocols: research notes, 20 October 2026

Purpose: decide how telescopeyoke could support mounts other than the
Sky-Watcher SynScan handset (and the Sky-Watcher motor board it already
drives directly). Notes, not a spec.

Marking used below:
- **[doc]**: read in the manufacturer's own document (PDF fetched and read).
- **[src]**: read in driver source code (INDI, INDIGO, alpyca) on GitHub.
- **[forum]**: user reports, retailer or blog pages; plausible, not proven.
- **[guess]**: my inference; check before building on it.

---

## 0. What telescopeyoke sends today, and the surprises found

The project sends to the SynScan handset: `K`, `V`, `m`, `J`, `H`/`h`, `W`,
`e`, `z`, `r`, `M`, `L`, `T`, and `P` passthrough (dev 16/17; `P 2 … 36/37`
fixed rate, `P 3 … 6/7` variable rate). `mount.py` reads `z` as "raw axis
angles" (`mount.py:116`, `HOME_DEC_AXIS = 90`) and sets tracking with
`T` + chr(2) (`mount.py:265`).

Three findings bear on the existing code, not just on new mounts:

1. **`z` is documented as precise Az/Alt, not axis positions, by both
   makers.** Sky-Watcher's own protocol v3.3 [doc] lists `z` as "Get precise
   AZM-ALT", and the SynScan V4 firmware **4.39.21** release note (dated
   20 April 2022 on Sky-Watcher's download page) says it "update[s] the serial
   commands 'Z' and 'z' that these two will coincide with their definition in
   SynScan Serial Communication Protocol version 3.3" [forum: release note
   quoted by search, not opened]. Reading: older firmware on EQ mounts
   returned raw axis positions; newer firmware returns true Az/Alt. **A
   handset firmware update could silently change what `mount.py` reads.**
   [guess] The project should record the handset version (`V`) with the axis
   readings and refuse, or switch to the motor-board path, on firmware
   ≥ 4.39.21 until tested.
   The documented way to read raw axis angles through the handset is not in
   v3.3; the SynScan **App** protocol has `Action,AxisCoordinatesGet`
   ("raw uncompensated axis value") [doc], and the motor board's `:j` reads
   them directly.
2. **`T` mode numbers differ between makers.** NexStar: 0 off, 1 Alt/Az,
   2 EQ North, 3 EQ South [doc]. SynScan: 0 off, 1 Alt/Az, 2 Equatorial,
   3 PEC mode (sidereal + PEC) [doc]. `T 2` is right for both in the north;
   a southern-hemisphere Celestron needs 3, and 3 on a SynScan means PEC.
   NexStar also warns CGE/Advanced GT HC 3.01–3.04 used 1 = EQ N, 2 = EQ S.
3. **SynScan has a pier-side command, `p`**, returning `E#` or `W#` ("E" =
   not flipped, OTA east of the meridian, in the north) [doc]. Celestron's
   newer handsets answer `p` the same way [src: INDI `celestrondriver.cpp`
   `get_pier_side`]. Useful for the "east/west readout" open item.

---

## 1. Celestron NexStar hand-control protocol

Primary source: *NexStar Communication Protocol* (Celestron, A. Paquette,
2006) [doc]
https://s3.amazonaws.com/celestron-site-support-files/support_files/1154108406_nexstarcommprot.pdf
Compared line by line with Sky-Watcher's *SynScan Serial Communication
Protocol v3.3* (2016/2018) [doc]
https://inter-static.skywatcher.com/downloads/synscanserialcommunicationprotocol_version33.pdf

**Link**: both 9600 baud, 8N1, via the RS-232 jack on the hand controller
[doc, both]. Response timeout: NexStar says be ready to wait up to **3.5 s**,
SynScan **5.0 s**; never send blind [doc, both].

### Command-by-command against what telescopeyoke uses

| Cmd | NexStar (Celestron doc) | SynScan v3.3 | Same? |
|---|---|---|---|
| `K`+x | echo, `x#` (HC 1.2+) | echo, `x#` | identical |
| `V` | `chr(major) chr(minor) #` — **2 binary bytes** | **6 ASCII hex digits** + `#` (04.37.07 → `042507#`) | **differs**: parse by length |
| `m` | 1 GPS, 3 i-Series, 4 i-Series SE, 5 CGE, 6 Advanced GT, 7 SLT, 9 CPC, 10 GT, 11 4/5 SE, 12 6/8 SE (HC 2.2+) | 0 EQ6, 1 HEQ5, 2 EQ5, 3 EQ3, 4 EQ8, 5 AZ-EQ6, 6 AZ-EQ5, 128–143 AZ, 144–159 Dob, 160 AllView | same command, **different tables** — code values overlap (3, 4, 5, 6 mean different mounts) so `m` cannot tell maker; `V` length can |
| `J` | `chr(1|0)#` | same | identical |
| `H`/`h` | 8 binary bytes Q R S T U V W X (local time, zone, DST) (HC 2.3+) | same layout | identical |
| `W`/`w` | 8 binary bytes lat d m s N/S, lon d m s E/W (2.3+) | same | identical |
| `E`/`e` | RA/Dec as hex fraction of a turn, 16-bit / 32-bit (`e` HC 1.6+) | same; SynScan states **J2000** | identical format; epoch stated only by SW [doc]. [guess] Celestron is also J2000 on modern HCs — INDI treats both as JNow/J2000 by setting; check |
| `Z`/`z` | **AZM-ALT** (`z` precise, HC 2.2+). Before alignment, relative to power-on position; after, Az from N, Alt 0 = tube ⟂ az axis | **AZM-ALT**, documented identically | **identical on paper**; on an EQ the "Alt-Az" before alignment is an axis reading, hence the project's use. See §0.1 |
| `R`/`r` | GoTo RA/Dec (`r` 1.6+); fails unless aligned | same; SW adds "GoTo RA/Dec enables tracking if stopped" | identical |
| `B`/`b` | GoTo Az/Alt | same | identical |
| `S`/`s` | Sync RA/Dec (HC 4.10+) | same (HC 3.37+ / 4.37.03+) | identical, firmware-gated |
| `M` | cancel GoTo | same | identical |
| `L` | ASCII `0`/`1` + `#` | same | identical |
| `T`/`t` | modes 0 off, 1 AltAz, 2 EQ N, 3 EQ S | 0 off, 1 AltAz, 2 EQ, 3 PEC | **differs** (see §0.2) |
| `P` 2/3 | dev **16 = AZM/RA, 17 = ALT/DEC**; fixed rate `P 2 dev 36|37 rate 0 0 0`; variable `P 3 dev 6|7 hi lo 0 0`, rate = arcsec/s × 4 | identical bytes and device ids | **identical** |
| `P` dev version | `P 1 dev 254 0 0 0 2` → motor firmware | same | identical |
| `p` | not in the 2006 PDF; newer HCs return `E#`/`W#` [src INDI] | `E#`/`W#` [doc] | similar |

Both docs say fixed-rate slews at 1 or 2 do not override equatorial
tracking "useful to simulate autoguiding"; otherwise stop tracking, slew,
restart [doc, both]. NexStar GT: rate 9 is 3°/s only.

`P` error convention [NexStar doc]: if a passthrough gets no answer from the
device, one extra garbage byte comes before `#`; drivers should check that
the reply ends with `#` and swallow one more byte if not. Not stated in the
SynScan doc.

Device ids beyond 16/17 [NexStar doc / INDI src]: 176 (0xB0) GPS, 178 RTC
(CGE), 0x12 focuser (Celestron focus motor) [src `celestrondriver.h`].

### Celestron extras the project would need (from INDI source, not the 2006 doc)

From `indilib/indi drivers/telescope/celestrondriver.{h,cpp}` [src]
https://github.com/indilib/indi/blob/master/drivers/telescope/celestrondriver.cpp
- `v` variant: distinguishes NexStar+ (0x11) from StarSense HC; "only
  available for NexStar+ 5.28 or more and StarSense".
- `u` unsync ("NS+ 5.28 and more only, not StarSense").
- `I`/`i` precise time (zone in quarter hours); `x`/`y` hibernate/wake;
  `Y` last-align; `P … 0x0B/0x12` move to index (CGX/CGEM II switches).
- **Pulse guide is a motor passthrough, not the 6/7 variable rate**:
  `MTR_AUX_GUIDE = 0x26` with rate −100…100 (% sidereal) and duration in
  centiseconds (max 2.55 s); `0x27` asks if a pulse is still running;
  `0x46`/`0x47` set/get autoguide rate. INDI header calls it "experimental".
  [guess] Sky-Watcher motor boards behind a SynScan HC are not known to
  accept 0x26; telescopeyoke's `P 3 … 6/7` approach is the portable one.

### Which mounts, which link

- The 2006 doc lists: NexStar GPS, GPS-SA, iSeries, SE, GT, CPC, SLT,
  Advanced-GT, CGE [doc]. INDI's `drivers.xml` [src] maps **NexStar HC, CPC
  HC, Advanced VX HC, CGEM HC, CGX HC, Celestron GPS** all to
  `indi_celestron_gps`, i.e. the same HC protocol covers NexStar SE,
  Evolution (through its HC), AVX, CGEM/CGEM II, CGX/CGX-L, CPC.
- NexStar+ HC has its own USB socket presenting a serial port [forum,
  widely reported; unconfirmed here]. Older HCs: RS-232 via the HC's
  bottom jack (9600).
- **StarSense AutoAlign**: a replacement HC that speaks the same HC protocol
  (INDI detects it via `v`; version numbers ~1.x overlap early NexStar
  versions) [src]. StarSense *Explorer* is a phone-app Dob with no motors:
  not a target.
- **Celestron AUX bus (no HC)**: Evolution's built-in Wi-Fi and the SkyPortal
  /SkyFi Wi-Fi module speak the raw **AUX** protocol over TCP, default
  **1.2.3.4:2000** [src `indi-3rdparty/indi-celestronaux/auxproto.h`]; the
  mount's PC/AUX port is **19200 baud with RTS/CTS** [src
  `celestronaux.cpp`]. That driver is "BETA… no slew limits" [src README].
  So **Wi-Fi Celestrons need an AUX driver, not the HC protocol**.
- Celestron Origin: own system; INDI has `indi-celestron-origin` in
  3rdparty [src: repo listing]. Not researched further.
- Celestron's Windows route is CPWI (its ASCOM driver, talks AUX)
  [forum].

**Verdict**: a NexStar backend is ~90 % shared with the SynScan class:
same framing, coords, GoTo, sync, slew passthrough, time/site. Differences
to code: `V` parse, `m` table, `T` mode table, 3.5 s timeout, the `P`
no-reply convention, and the meaning of `z` (true Az/Alt on Celestron;
the project would need `P 1 dev 0x01 … 3` "MC_GET_POSITION" for raw axis
counts [src `MC_GET_POSITION 0x01` returns 24-bit position]).

---

## 2. Meade LX200 and its dialects

Primary source: *Meade Telescope Serial Command Protocol*, Revision 2007.10
(Autostar, LX200 <16", LX 16", Autostar II) [doc]
https://www.weasner.com/etx/autostar/2010/AutostarSerialProtocol2007oct.pdf
(mirror; Meade's own URL no longer resolves; Meade went into
receivership in 2024 [forum]).

Format: ASCII, `:` + command + `#`. Classic LX200 9600 baud 8N1 [doc:
`:SBn#` table; widely known]. Autostar II / LX200GPS may answer any command
with NAK 0x15 within 10 ms if busy: wait and retry [doc].

| Function | Command (reply) [doc] |
|---|---|
| Get RA / Dec | `:GR#` → `HH:MM.T#` or `HH:MM:SS#`; `:GD#` → `sDD*MM#` or `sDD*MM'SS#`; `:U#` toggles low/high precision |
| Set target | `:SrHH:MM:SS#` (or `HH:MM.T`), `:SdsDD*MM:SS#` → `1`/`0` |
| GoTo | `:MS#` → `0` ok, `1<msg>#` below horizon, `2<msg>#` below "higher" limit |
| Sync | `:CM#` → text string (object name) |
| Stop | `:Q#` all; `:Qe# :Qn# :Qs# :Qw#` per direction |
| Manual move | `:Me# :Mn# :Ms# :Mw#` at current rate |
| Slew rate | `:RG#` guide, `:RC#` centre, `:RM#` find, `:RS#` max; `:RgSS.S#` guide rate (Autostar II) |
| Pulse guide | `:MgnDDDD# :MgsDDDD# :MgeDDDD# :MgwDDDD#` ms; returns nothing; **"LX200 – Not supported"** (classic) |
| Park | `:hP#` (Autostar, LX200GPS, LX 16") |
| Tracking | `:TQ#` sidereal, `:TL#` lunar, `:TM#` custom, `:TTTT.T#`-family rates |
| Time/site | `:SL`, `:SC`, `:SG`, `:St`, `:Sg` |
| Alignment query | ACK (0x06) → mount mode |

There is no standard LX200 "pier side", "tracking on/off", "is slewing" or
"unpark"; each maker adds its own → **"LX200" is a family, not a protocol**.
INDI's tree shows this: `lx200generic` plus ~20 subclasses [src].

### Who speaks it

- **ZWO AM3 / AM5 / AM5N / AM7** — **[doc] ZWO Mount Serial Communication
  Protocol v2.1 (6 Feb 2026)**, published in INDIGO's repo:
  https://github.com/indigo-astronomy/indigo/tree/master/indigo_drivers/mount_asi/docs
  "The Protocol is based on LX200 also compatible with LX200." Serial
  **9600 baud** (USB); Wi-Fi via the hand controller's AP **192.168.4.1
  port 4030** (INDI's `lx200am5.cpp` uses TCP 4030 [src]). Commands include
  `:GR# :GD# :Sr :Sd :MS# :CM# :Q# :Qe/w/n/s# :Me/w/n/s#`, `:Mgdnnnn#`
  pulse guide (0–3000 ms), `:Rg0.nn#`/`:Ggr#` guide rate 0.10–0.90×,
  `:Te# :Td#` tracking on/off, `:GU#` status, `:hC#` home, `:hP#` park
  (v1.7+), custom park/unpark/park-status (v2.1), meridian behaviour
  `:STa…`, altitude limits, `:Rvnnnn.nn#` variable speed, `:AA#/:AP#`
  alt-az/EQ mode, BLE commands (v2.0). Time and site must be set before
  GoTo works. A forum report says `:Mg` returned OK but did nothing on
  firmware 1.8.8 [forum: bbs.zwoastro.com/d/26117]. ZWO also ships a
  Windows ASCOM driver [forum]; **no native Alpaca found**.
- **OnStep / OnStepX** (open-source DIY and several commercial mounts:
  INDI lists WARPDRIVE, EM31Pro, Juwei 14/17, SAL-33 on `indi_lx200_OnStep`
  [src drivers.xml]) — extended LX200 (`:GU#` status string, `:GX..#`
  extensions) [src `lx200_OnStep.cpp`]. Wi-Fi/Ethernet LX200 command server
  **TCP 9999** (standard) or 9996–9998 (persistent) [src OnStepX
  `WifiManager.defaults.h`]. ASCOM (COM) driver exists; **no native Alpaca
  found** [forum].
- **iOptron** — its own **"iOptron Mount RS-232 Command Language"**
  (v2.0 Aug 2014 for CEM60/iEQ45 Pro; v2.5 Jan 2019; v3.10 Jan 2021)
  [forum: copies at
  https://casite-460905.cloudaccess.net/media/kunena/attachments/687/iOptronMountRS-232Commandlanguage2014-2.pdf
  and the Python driver docs https://ioptron-for-python.readthedocs.io/].
  LX200-*shaped* (`:…#`) but different commands: `:MountInfo#`, `:GLS#`
  (23-char status: long/lat/GPS/system state/tracking/time source…),
  `:GEP#` (RA, Dec and pier side together), `:SRA`/`:Sd`, `:MS1#` GoTo,
  `:Q#`, `:MP1#` park / `:MP0#` unpark, `:MH#` home, `:ST0/1#` tracking,
  `:RT0-4#` rates, pulse guide `:ZE|ZC|ZQ|ZS nnnnn#` (ms) on v3 firmware,
  `:SUT`/`:SLA`/`:SLO` time/site [src INDI `ioptronv3driver.cpp`, "for
  firmware 20171001 or later"]. INDI defaults: **115200 baud** (230400 for
  CEM120), Wi-Fi **10.10.100.254:8899** [src `ioptronv3.cpp`]. Older
  models (ZEQ25, iEQ30/45) used an LX200-like set
  (`indi_lx200zeq25`); iEQ45 Pro/CEM60/CEM25/SmartEQ use the v2 language
  (`indi_ieq_telescope`); CEM26/GEM28/CEM40/GEM45/CEM70/CEM120/HEM/HAE use
  v3 (`indi_ioptronv3_telescope`) [src drivers.xml]. **Needs its own
  backend.**
- **Losmandy Gemini (Gemini-1/2)** — LX200 subset plus Gemini native
  commands; INDI `indi_lx200gemini` with pulse guiding [src]. Gemini-2 also
  has Ethernet/UDP [forum, unconfirmed details].
- **10Micron** — LX200-derived "Mount Command Protocol 2.14.11" with
  extensions; INDI `indi_lx200_10micron` declares tracking-frequency and
  pulse guiding [src]. Ethernet is the normal link [forum].
- **Avalon (StarGo / StarGo2)** — LX200 with `:X…` extensions;
  `indi-3rdparty/indi-avalon` (StarGo + its AUX focuser), `indi-avalonud`
  for the newer Unified Driver [src: repo listing].
- **Rainbow Astro RST-135/300** — LX200-style own set, **115200 baud**;
  INDI `indi_rainbow_telescope` [src `rainbow.cpp`].
- Others in INDI's LX200 tree [src]: Astro-Physics GTOCP (`lx200ap_*`),
  Pegasus NYX-88/101, OpenAstroTech, TeenAstro, PMC-Eight is *not* LX200
  (own driver), Pulsar2, GotoNova, FS-2, SkySensor 2000, Argo Navis,
  Mel Bartels, ESP32go, Meade LX90/ETX/LX200GPS/Autostar.
- **Sky-Watcher: none.** SynScan speaks the NexStar-style protocol; Sky-Watcher
  publishes no LX200 mode [doc: its developer page lists only SynScan serial,
  motor command set and SynScan App protocol].

**Verdict**: one "LX200 core" class (`:GR#/:GD#/:Sr/:Sd/:MS#/:CM#/:Q#/:Mx#/:Mg`)
plus per-maker subclasses for status, tracking, park and pier side. AM5
is the most valuable and best documented (free official PDF, simple,
9600/TCP 4030). OnStep second (open source). iOptron is a separate backend.

---

## 3. INDI telescope standard

Property names below are read from `libs/indibase/inditelescope.cpp` and
`indiguiderinterface.cpp` [src]
https://github.com/indilib/indi/blob/master/libs/indibase/inditelescope.cpp
(the old indilib.org standard-properties page URL now 404s).

What a client needs:

| Property | Elements | Use |
|---|---|---|
| `EQUATORIAL_EOD_COORD` (number) | `RA` (hours), `DEC` (deg) | current JNow position; writing it starts the action chosen in `ON_COORD_SET` |
| `ON_COORD_SET` (switch) | `TRACK`, `SLEW`, `SYNC` | GoTo-and-track / GoTo / sync |
| `TARGET_EOD_COORD` | `RA`, `DEC` | slew target (read-only) |
| `TELESCOPE_ABORT_MOTION` | `ABORT` | stop |
| `TELESCOPE_PARK` | `PARK`, `UNPARK` | park; `TELESCOPE_PARK_POSITION`, `TELESCOPE_PARK_OPTION` |
| `TELESCOPE_HOME` | (find/set/go home) | newer drivers |
| `TELESCOPE_TRACK_STATE` | `TRACK_ON`, `TRACK_OFF` | |
| `TELESCOPE_TRACK_MODE` | `TRACK_SIDEREAL`, solar, lunar, `TRACK_CUSTOM` | |
| `TELESCOPE_TRACK_RATE` | RA/Dec custom rates | |
| `TELESCOPE_MOTION_NS` / `_WE` | `MOTION_NORTH/SOUTH`, `MOTION_WEST/EAST` | manual move at `TELESCOPE_SLEW_RATE` |
| `TELESCOPE_TIMED_GUIDE_NS` / `_WE` | `TIMED_GUIDE_N/S`, `TIMED_GUIDE_W/E` (ms) | pulse guide |
| `GUIDE_RATE` | RA/Dec × sidereal | driver-dependent |
| `TELESCOPE_PIER_SIDE` | `PIER_EAST`, `PIER_WEST` | |
| `TIME_UTC` | `UTC`, `OFFSET` | |
| `GEOGRAPHIC_COORD` | `LAT`, `LONG`, `ELEV` | |
| `HORIZONTAL_COORD` | `AZ`, `ALT` | alt-az capable drivers |
| `TELESCOPE_INFO`, `TELESCOPE_MOUNT_TYPE`, `TELESCOPE_REVERSE_MOTION` | | |

State is reported per property (Idle/Ok/Busy/Alert): Busy on
`EQUATORIAL_EOD_COORD` = slewing. Driver-specific extras (meridian flip
settings, limits) are not standard.

**Drivers**: INDI core `drivers.xml` lists **100 entries in the Telescopes
group** (counted 20 Oct 2026, many share a binary) [src]
https://github.com/indilib/indi/blob/master/drivers.xml . Core binaries
include: `indi_synscan_telescope` (SynScan HC, warns below HC 3.38 / 4.38
[src]), `indi_skywatcherAltAzMount` (motor protocol, UDP 11880, AZ-GTi
Wi-Fi/wired) [src], `indi_celestron_gps`, `indi_lx200am5` (ZWO AM3/5/7
USB+Wi-Fi), `indi_lx200_OnStep`, `indi_ieq_telescope` /
`indi_ioptronv3_telescope`, `indi_lx200gemini`, `indi_lx200_10micron`,
`indi_lx200ap_v2`, `indi_rainbow_telescope`, `indi_pmc8_telescope`,
`indi_paramount_telescope`, `indi_planewave_telescope`,
`indi_temma_telescope`, `indi_lx200_pegasus_nyx101`, and since 2026
**`indi_alpaca_telescope`** (an INDI driver that *talks to* an Alpaca
mount; © 2026 Gord Tulloch) [src]. 3rd-party repo adds **`indi-eqmod`**
(all Sky-Watcher/Orion EQ mounts by motor protocol, serial or UDP),
`indi-celestronaux`, `indi-celestron-origin`, `indi-avalon`,
`indi-avalonud`, `indi-starbook`, `indi-starbook-ten` [src: repo listing].
INDIGO (separate framework) has its own set: `mount_synscan`,
`mount_nexstar`, `mount_nexstaraux`, `mount_lx200`, `mount_asi`,
`mount_ioptron`, `mount_rainbow`, `mount_pmc8`, `mount_starbook`,
`mount_temma`, plus `agent_alpaca` [src].

**Would an INDI client give broad support on Linux?** Yes [judgement]:
one client against ~15 standard properties reaches essentially every mount
an amateur owns, with maintained drivers, and telescopeyoke already has an
INDI client for cameras. Costs: the user must install and run `indiserver`
with the right driver (INDI packages are standard on Ubuntu via the PPA);
a second layer between the project and the mount (the project's safety
checks — motion lock, dry runs, limits — must sit in front of the INDI
calls, and a driver's own GoTo may take a path the project did not plan);
behaviour beyond the standard properties varies per driver; **INDI does not
run on Windows**, so it does not serve the Windows port.

---

## 4. ASCOM Alpaca

Spec: Alpaca Device API OpenAPI file (Platform 7) [doc]
https://github.com/ASCOMInitiative/ASCOMRemote/blob/master/Swagger/AlpacaDeviceAPI_v1P7.yaml
(rendered at https://ascom-standards.org/api/), management API
`AlpacaManagementAPI_v1.yaml` alongside; developer intro
https://ascom-standards.org/AlpacaDeveloper/Index.htm ; reference
https://ascom-standards.org/AlpacaDeveloper/ASCOMAlpacaAPIReference.html

**Shape**: HTTP REST, `/api/v1/telescope/{device_number}/{member}`; `GET`
for properties (query string), `PUT` for methods and setters
(form-urlencoded body); every call may carry `ClientID` and
`ClientTransactionID`; replies are JSON with `Value`, `ErrorNumber`,
`ErrorMessage`, `ClientTransactionID`, `ServerTransactionID` [doc].
Management: `/management/apiversions`, `/management/v1/description`,
`/management/v1/configureddevices` [doc].

**Telescope members** (all present in the v1P7 spec) [doc]:
`slewtocoordinatesasync`, `slewtoaltazasync`, `slewtotargetasync` (sync
variants exist but are deprecated in ITelescopeV4), `abortslew`, `slewing`,
`synctocoordinates`, `synctoaltaz`, `park`, `unpark`, `atpark`, `setpark`,
`findhome`, `athome`, `pulseguide` (Direction 0–3, Duration ms),
`ispulseguiding`, `guideraterightascension`/`declination`, `moveaxis`
(Axis, Rate deg/s) with `axisrates` (GET, per axis) and `canmoveaxis`,
`tracking` (GET/PUT), `trackingrate`, `trackingrates`,
`rightascensionrate`/`declinationrate`, `sideofpier` (GET/PUT = flip),
`destinationsideofpier`, `rightascension`, `declination`, `altitude`,
`azimuth`, `siderealtime`, `utcdate`, `sitelatitude/longitude/elevation`,
`equatorialsystem`, `alignmentmode`, `doesrefraction`, and the `can*`
capability flags.

**Discovery** [src alpyca `discovery.py`]: client broadcasts the ASCII
string `alpacadiscovery1` to **UDP 32227** (IPv6 multicast `ff12::a1:9aca`);
each server answers JSON `{"AlpacaPort": n}`; then query
`/management/v1/configureddevices` on that port.

**Who offers Alpaca natively**: I found **no amateur GEM with Alpaca in
its own firmware** (ZWO AM5: ASCOM COM driver + LX200 serial; Sky-Watcher:
none; OnStepX: COM driver + LX200 over IP; iOptron: COM) [forum, negative
results; treat as "not found", not "proven absent"]. Reported native
Alpaca: ZWO **Seestar** smart telescopes in recent firmware [forum: single
blog]. Alpaca reaches mounts mostly via servers:
- **ASCOM Remote** (Windows): exposes any installed COM driver
  (EQMOD, GS Server, ZWO, iOptron Commander, CPWI…) as Alpaca so Linux/Mac
  clients can use it [doc: ascom-standards.org/FAQs/Index.htm].
- **INDIGO `agent_alpaca`**: exposes INDIGO's drivers as an Alpaca server
  on Linux/Pi [src].
- Third-party SBC servers (e.g. open-astro/AlpacaBridge, claims Celestron,
  iOptron, OnStep, Sky-Watcher) [forum, self-reported].
- ASCOM Platform 7's Chooser makes Alpaca devices appear as COM drivers to
  Windows apps [doc].
- Simulators: ASCOM.Alpaca.Simulators (OmniSim) for testing [doc].
- Python client: **alpyca** (`pip install alpyca`), official [doc].

**Is Alpaca a reasonable cross-platform route?** As a *client* in
telescopeyoke: yes [judgement] — small (HTTP + JSON), same code on Ubuntu
and Windows, has a free simulator, and on **Windows** it is the clean way
to reach every ASCOM driver (run ASCOM Remote locally, or Platform 7
dynamic clients the other way). It is not "plug the mount in and go" on
Linux: something must serve Alpaca (INDIGO, ASCOM Remote on a PC, a bridge).

---

## 5. Sky-Watcher variants

Sky-Watcher's developer page [doc]
https://www.skywatcher.com/download/manual/application-development/ lists
three protocols:

1. **SynScan HC serial protocol v3.3** (above): only when a SynScan
   handset is in the chain; RS-232 9600 on the handset (V5 handsets have
   USB) [doc].
2. **Motor controller command set** (EQMOD protocol) [doc]
   https://inter-static.skywatcher.com/downloads/skywatcher_motor_controller_command_set.pdf :
   `:` + cmd + CR; UART **9600 8N1**, 5 V or 3.3 V; on most EQ mounts TX/RX
   separate, on most Alt/Az mounts a shared TX/RX bus with a "Drop" line.
   **"The same protocol runs on the SynScan Wi-Fi dongle or mount with
   built-in Wi-Fi module"**: **UDP 11880**, one command per packet, AP
   address 192.168.4.1. Mounts with a USB-B socket on the body (EQ6-R Pro,
   newer HEQ5 Pro/AZ-EQ6, EQ8-R, EQM-35) use this protocol at **115200**
   through an on-board Prolific USB-serial [forum: IceInSpace, HPS guide,
   Astropical "will not connect at 9600"].
3. **SynScan App Protocol** (2025-09-30) [doc]
   https://inter-static.skywatcher.com/downloads/synscan_app_protocol_20250930.pdf :
   the SynScan / SynScan Pro **app** acts as a server on **UDP or TCP
   11881**; text commands are a one-to-one translation of ASCOM
   ITelescopeV3 (`SlewToCoordinatesAsync,12.45,45.89` →
   `Ok,SlewToCoordinatesAsync`), plus `Action,AxisCoordinatesGet`,
   `AzimuthAltitudeGet`, `RightAscensionDeclinationGet`, `ConnectedSet`.
   Only async slews. Responses up to ~800 ms over poor Wi-Fi.
   Separately, SkySafari connects to the SynScan app on **TCP 11882**
   [forum: Simulation Curriculum support threads]; [guess] that port speaks
   the handset serial protocol so planetarium apps' "SynScan" drivers work.

Per mount [mostly forum + INDI src; mark as unconfirmed unless noted]:

| Mount | Built-in link | Protocol on it |
|---|---|---|
| AZ-GTi, AZ-GTix, AZ-GTe | Wi-Fi (no handset by default); HC port optional | motor protocol UDP 11880 [src: INDI `AZ-GTi Alt-Az WiFi` → `skywatcherAPIMount`, UDP 11880]; EQ mode after firmware; HC protocol only if a SynScan handset is plugged in |
| Star Adventurer GTi | Wi-Fi + HC port | motor protocol UDP 11880 [forum]; indi-eqmod supports it [forum] |
| EQM-35 Pro, EQ6-R Pro, HEQ5 Pro (recent), AZ-EQ5/AZ-EQ6, EQ8-R | USB-B on body (115200), HC port; Wi-Fi by dongle | motor protocol on USB/EQDIR/dongle; HC protocol through handset [forum] |
| EQ3 Pro / EQ5 Pro (the user's EQ3) | HC port only; Wi-Fi by dongle | HC protocol via handset; motor protocol via EQDIR cable or SynScan Wi-Fi dongle (11880) |
| Wave 100i / 150i (strain-wave) | Wi-Fi + USB built in | motor protocol (indi-eqmod/GS Server list them) [forum, unconfirmed] |

So every Sky-Watcher GoTo mount answers the **motor protocol** somewhere;
only handset-equipped ones answer the HC protocol. telescopeyoke's existing
direct path (`direct.py`) is therefore the one that covers the whole brand.
GS Server (Windows, ASCOM) speaks the motor protocol to "EQ6-R Pro, AzGTi,
HEQ5…" [doc: ascom-standards.org/Downloads/ScopeDrivers.htm].

---

## 6. Popularity (rough)

Hard numbers are scarce. What exists:
- APOTY shortlist analysis, 828 images over six years to 2023 (A. Robinson,
  reposted by Sky-Watcher USA, Apr 2024) [forum-grade data]
  https://skywatcherusa.com/blogs/news/2023-astronomy-photographer-of-the-year-gear-analysis-sky-watcher-mounts-edition-1 :
  Sky-Watcher 33 % of all images; **EQ6-R Pro 14 %** (most used single
  model), NEQ6 Pro 5 %; planetary EQ6-R 15 %, EQ8 6 %, HEQ5 5 %; 2021–23
  EQ6-R 11 %, EQ8 6 %; 2023 mount types 53 % equatorial, 22 % direct drive,
  9 % harmonic; Star Adventurer 36 % of tracker use. (Award entries skew
  premium; not a beginner census.)
- AstroBin polls: AM5 vs CEM70 151 votes, 78 to 73 [forum]; AM5 vs EQ6-R
  near-even [forum]. Shows AM5 sits in the same consideration set as EQ6-R.
- Retail/review roundups (HPS 2026, Sky at Night 2025, AstroBackyard 2025)
  consistently feature: Star Adventurer GTi, AZ-GTi, HEQ5 Pro, EQ6-R Pro,
  ZWO AM5, iOptron CEM26/CEM40/GEM28, Celestron AVX/CGEM II/CGX [forum].

Rough ranking for beginner/intermediate imagers 2024–26 [judgement]:
1. Sky-Watcher HEQ5 Pro / EQ6-R Pro (and AZ-EQ6) — the default GEMs.
2. ZWO AM5 / AM3 — the fast-rising strain-wave choice, especially with ASIAIR.
3. Sky-Watcher Star Adventurer GTi / AZ-GTi — entry level, Wi-Fi.
4. iOptron CEM26/GEM28/CEM40/HEM27.
5. Celestron AVX / CGEM II / CGX; NexStar SE and Evolution for visual/EAA.
6. EQ3/EQ5 Pro SynScan class (the user's own) — common second-hand.
Smaller: OnStep DIY, Rainbow, Losmandy, Avalon, 10Micron, Pegasus NYX.

---

## Planning summary [judgement]

- **Nearly free**: Celestron HC (NexStar SE/Evolution-via-HC/AVX/CGEM/CGX/CPC
  and StarSense HC) — subclass the SynScan handset class: same framing,
  coords, `e/r/s/M/L/J/H/W/K`, same `P` 16/17 36/37 and 6/7. Change `V`,
  `m`, `T` table, timeout, `z` meaning.
- **All Sky-Watcher**: already covered by the motor-protocol path once its
  transports include USB 115200 and UDP 11880 (AZ-GTi, SA GTi, EQ6-R, Wave).
- **Generic routes**: INDI client for mounts (Linux; reuses the camera
  client; ~100 driver entries) and Alpaca client (Linux + Windows; reaches
  every ASCOM driver via ASCOM Remote; INDIGO can serve Alpaca on Linux).
- **Own driver worth writing**: ZWO AM3/5/7 (official LX200-based PDF,
  9600 or TCP 4030) on an "LX200 core" that OnStep (TCP 9999) also fits.
- **Leave to INDI/Alpaca**: iOptron (own language, 115200, Wi-Fi 8899),
  Celestron AUX/Wi-Fi (TCP 2000, beta driver upstream), Gemini, 10Micron,
  Avalon, Rainbow, PMC-Eight.
- **Fix now in existing code**: record handset firmware; guard `z` against
  firmware ≥ 4.39.21; consider SynScan `p` for pier side.
