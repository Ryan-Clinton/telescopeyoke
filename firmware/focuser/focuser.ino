// The focuser's motor: a 17HS4401 NEMA 17 on a TMC2209 driver (black carrier
// board, 12 V, microstep switches all off: 1/8, 1600 microsteps a turn),
// EN on D8, STEP on D9, DIR on D10 of an Arduino Nano. focuser.py loads
// this and talks to it. (Until 9 November 2026: a 28BYJ-48 on a ULN2003
// board, IN1..IN4 on D4..D7.)
//
// Moves are still counted in the old motor's half-steps, 4096 to a turn of
// the shaft, so every figure kept in half-steps (the travel, filter offsets,
// walk-in steps) still means the same turn of the focuser's knob. 4096
// half-steps are 1600 microsteps, 25 to every 64: the firmware keeps the
// remainder, so moves out and back in again come to the same microstep.
//
// Orders are whole lines at 9600 baud, each starting with a colon, so stray
// bytes meant for something else (a mount's handset, say) move nothing:
//
//   :?         -> "TY focuser 1"
//   :M+1024    -> "OK 1024" once the motor has turned that many half-steps
//   :M-1024    -> the same, the other way
//   :S40       -> "OK S40": 40 ms a half-step from now until the Nano restarts
//                 (opening its port restarts it); 2 to 200
//   :F1, :F0   -> "OK F1", "OK F0": the old motor's two-coil stepping, kept
//                 so focuser.py's orders still answer; nothing changes
//   :H1, :H0   -> "OK H1", "OK H0": the driver kept on between moves, holding
//                 the shaft, or off when still (the default) until the Nano
//                 restarts; for a drawtube that slips with it off
//   :T         -> "T 512": the thermistor's reading, 0 to 1023, the average of
//                 16. A 10 kOhm NTC from A0 to GND and 10 kOhm from A0 to A5,
//                 which is held high as their 5 V (31 October 2026);
//                 focuser.py turns it into degrees. About 1023 is no
//                 thermistor, about 0 a short.
//   :V         -> "V 1104": millivolts on A2, the average of 16, measured
//                 against the Nano's own 1.1 V reference rather than trusting
//                 its 5 V (about 4.7 V on USB). A wire from A2 to the TMC2209's
//                 pot sets the motor's current without a meter (9 November
//                 2026); focuser.py vref shows it as it is turned. "V -1" is
//                 nothing on A2: a bare pin reads any voltage at all, so it is
//                 first pulled up weakly, which the pot holds down and a bare
//                 pin follows to near 5 V.
//
// The driver is off (EN high) whenever the motor is still: a warm motor
// beside the tube spoils the seeing, and with no UART the TMC2209 would hold
// at full current. If the drawtube slips under the camera with it off, that
// is the thing to change.

const byte EN = 8;                 // low: the driver on
const byte STEP = 9;               // one pulse, one microstep
const byte DIR = 10;
const byte SENSE = A0;             // the thermistor and the resistor meet here
const byte SUPPLY = A5;            // the resistor's other end: high from the start
const byte PROBE = A2;             // :V, a wire to the driver's pot, only while setting it
const long MOST = 40960;           // ten turns of the shaft: more is a mistake
const int STEP_MS = 20;            // ms a half-step until :S says otherwise
int stepMs = STEP_MS;
bool full = false;                 // as :F sets it, for the answer only
bool hold = false;                 // as :H sets it: the driver stays on between moves
long halfSteps = 0;                // where the motor is since the Nano started, in half-steps
long micro = 0;                    // and in microsteps, as sent
String line;

long microFor(long half) {         // 25 microsteps to 64 half-steps, rounding down
  long scaled = half * 25;
  return scaled >= 0 ? scaled / 64 : -((-scaled + 63) / 64);
}

void turn(long steps) {
  halfSteps += steps;
  long target = microFor(halfSteps);
  long left = target - micro;
  if (left == 0) return;
  digitalWrite(DIR, left > 0 ? HIGH : LOW);
  delay(1);
  digitalWrite(EN, LOW);
  delay(200);                      // the driver wakes and tunes StealthChop at standstill
                                   // (9 November 2026: at 5 ms one direction only hummed)
  // the same time a half-step as before: 64 half-steps' worth over 25 microsteps
  unsigned long gap = (unsigned long)stepMs * 64000UL / 25;
  for (long i = labs(left); i > 0; i--) {
    digitalWrite(STEP, HIGH);
    delayMicroseconds(10);
    digitalWrite(STEP, LOW);
    delay(gap / 1000);
    delayMicroseconds(gap % 1000);
  }
  micro = target;
  delay(50);                       // let it settle before the coils go off
  if (!hold) digitalWrite(EN, HIGH);
}

long vccMillivolts() {             // the 5 V as it really is, from the 1.1 V bandgap
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
  delay(2);                        // let the reference settle
  long sum = 0;
  for (byte i = 0; i < 16; i++) {
    ADCSRA |= _BV(ADSC);
    while (bit_is_set(ADCSRA, ADSC)) {}
    sum += ADC;
  }
  return 1125300L * 16 / sum;      // 1.1 V x 1023 x 1000, over the reading
}

long probeMillivolts() {
  long vcc = vccMillivolts();
  pinMode(PROBE, INPUT_PULLUP);
  delay(5);
  analogRead(PROBE);
  bool bare = analogRead(PROBE) > 820;   // 4 V: the pot holds it nearer 1 V
  pinMode(PROBE, INPUT);
  if (bare) return -1;
  delay(5);
  analogRead(PROBE);               // the first reading after the switch is stale
  long sum = 0;
  for (byte i = 0; i < 16; i++) sum += analogRead(PROBE);
  return sum * vcc / (16L * 1023);
}

void obey(const String &order) {
  if (order == ":?") {
    Serial.println("TY focuser 1");
  } else if (order.startsWith(":M") && order.length() > 3
             && (order[2] == '+' || order[2] == '-')) {
    long steps = order.substring(2).toInt();
    if (steps == 0 || labs(steps) > MOST) { Serial.println("NO"); return; }
    turn(steps);
    Serial.print("OK ");
    Serial.println(steps);
  } else if (order.startsWith(":S") && order.length() > 2) {
    long ms = order.substring(2).toInt();
    if (ms < 2 || ms > 200) { Serial.println("NO"); return; }
    stepMs = ms;
    Serial.print("OK S");
    Serial.println(ms);
  } else if (order == ":F1" || order == ":F0") {
    full = order == ":F1";
    Serial.println(full ? "OK F1" : "OK F0");
  } else if (order == ":H1" || order == ":H0") {
    hold = order == ":H1";
    if (hold) { digitalWrite(EN, LOW); delay(200); } else digitalWrite(EN, HIGH);
    Serial.println(hold ? "OK H1" : "OK H0");
  } else if (order == ":T") {
    long sum = 0;
    for (byte i = 0; i < 16; i++) sum += analogRead(SENSE);
    Serial.print("T ");
    Serial.println(sum / 16);
  } else if (order == ":V") {
    Serial.print("V ");
    Serial.println(probeMillivolts());
  } else {
    Serial.println("NO");
  }
}

void setup() {
  digitalWrite(EN, HIGH);          // off before it is an output, so the motor never twitches
  pinMode(EN, OUTPUT);
  pinMode(STEP, OUTPUT);
  pinMode(DIR, OUTPUT);
  pinMode(SUPPLY, OUTPUT);
  digitalWrite(SUPPLY, HIGH);
  Serial.begin(9600);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (line.length()) obey(line);
      line = "";
    } else if (line.length() < 16) {
      line += c;
    } else {
      line = "";                   // not one of ours
    }
  }
}
