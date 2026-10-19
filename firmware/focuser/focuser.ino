// The focuser's motor: a 28BYJ-48 on a ULN2003 board, IN1..IN4 on D4..D7 of
// an Arduino Nano. focuser.py loads this and talks to it.
//
// Orders are whole lines at 9600 baud, each starting with a colon, so stray
// bytes meant for something else (a mount's handset, say) move nothing:
//
//   :?         -> "TY focuser 1"
//   :M+1024    -> "OK 1024" once the motor has made that many half-steps
//   :M-1024    -> the same, the other way
//   :S40       -> "OK S40": 40 ms a half-step from now until the Nano restarts
//                 (opening its port restarts it), for trying speeds; 2 to 200
//
// The coils are off whenever the motor is still: the gearbox holds the shaft,
// and a warm motor beside the tube spoils the seeing.

const byte PINS[4] = {4, 5, 6, 7};
const byte HALF[8] = {0b0001, 0b0011, 0b0010, 0b0110,
                      0b0100, 0b1100, 0b1000, 0b1001};
const long MOST = 40960;           // ten turns of the shaft: more is a mistake
const int STEP_MS = 20;            // slow, for torque: at 2 a half turn on the telescope fell short, and at 10 the motor lost half its steps against the drawtube on 19 October 2026
int stepMs = STEP_MS;              // as :S sets it, until the next restart
byte phase = 0;
String line;

void coils(byte bits) {
  for (byte i = 0; i < 4; i++) digitalWrite(PINS[i], (bits >> i) & 1);
}

void turn(long steps) {
  int dir = steps < 0 ? -1 : 1;
  for (long i = 0; i < abs(steps); i++) {
    phase = (phase + dir + 8) % 8;
    coils(HALF[phase]);
    delay(stepMs);
  }
  coils(0);
}

void obey(const String &order) {
  if (order == ":?") {
    Serial.println("TY focuser 1");
  } else if (order.startsWith(":M") && order.length() > 3
             && (order[2] == '+' || order[2] == '-')) {
    long steps = order.substring(2).toInt();
    if (steps == 0 || abs(steps) > MOST) { Serial.println("NO"); return; }
    turn(steps);
    Serial.print("OK ");
    Serial.println(steps);
  } else if (order.startsWith(":S") && order.length() > 2) {
    long ms = order.substring(2).toInt();
    if (ms < 2 || ms > 200) { Serial.println("NO"); return; }
    stepMs = ms;
    Serial.print("OK S");
    Serial.println(ms);
  } else {
    Serial.println("NO");
  }
}

void setup() {
  for (byte i = 0; i < 4; i++) pinMode(PINS[i], OUTPUT);
  coils(0);
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
