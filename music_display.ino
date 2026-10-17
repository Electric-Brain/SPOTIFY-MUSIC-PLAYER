// ============================================================================
//   SPOTIFY NOW PLAYING - PORTRAIT (VERTICAL) WITH 200x200 COVER ART
//   Hardware: Arduino UNO + MCUFRIEND 2.4" / 2.8" / 3.5" TFT Shield
// ============================================================================
// Fixes in this update:
//   1. 100% Reliable Full Image Render: Dedicated atomic 400-byte row read
//      guarantees zero serial FIFO buffer overflow. ACK 'K' is sent only AFTER
//      row is drawn and time is updated.
//   2. Immediate Track Reset: posSync & syncAt reset to 0 immediately on #SONG.
//      Time displays " 0:00" instantly (no old song timestamp like 0:21).
//   3. Fixed-width 5-char time strings eliminate trailing dashes/characters.
//   4. Clean progress bar: Scrubber knob clearance strictly managed.
// ============================================================================

#include <Adafruit_GFX.h>
#include <MCUFRIEND_kbv.h>

MCUFRIEND_kbv tft;

// ---------- Screen Rotation ----------
#define ROTATION 0 // 0 = Portrait (USB at bottom), 2 = Portrait (USB at top)

// ---------- Spotify Colors (RGB565) ----------
#define COL_BG          0x0000  // Pure black background
#define COL_SURFACE     0x1082  // #121212 dark surface
#define COL_BORDER      0x2945  // #282828 subtle borders
#define COL_GREEN       0x1EAC  // #1ED760 Vibrant Spotify green
#define COL_WHITE       0xFFFF  // Primary text / scrubber knob
#define COL_GRAY_LT     0xB576  // #B3B3B3 secondary text / duration
#define COL_GRAY_MD     0x7BEF  // #7A7A7A dim labels
#define COL_TRACK       0x39E7  // #3E3E3E progress bar groove

// ---------- Layout Dimensions (Portrait 240x320) ----------
#define HDR_H           28
#define ART_SIZE        200     // 200x200 Cover Art (Maximized width)
#define ART_X           20      // 20px margin on left, 20px on right
#define ART_Y           32      // y = 32..231
#define TXT_X           12
#define TITLE_Y         238     // y = 238..254 (TextSize 2)
#define ARTIST_Y        258     // y = 258..274 (TextSize 2)
#define BAR_X           12
#define BAR_W           216
#define BAR_Y           282     // Lowered duration bar
#define BAR_H           5
#define TIME_Y          294     // Lowered time counter
#define MAX_CH          18      // Visible chars in TextSize 2

// ---------- Sharp 24x24 Spotify Logo Bitmap (PROGMEM) ----------
const unsigned char PROGMEM logo24[] = {
  0x00, 0x7E, 0x00, 0x03, 0xFF, 0xC0, 0x07, 0xFF, 0xE0, 0x0F, 0xFF, 0xF0,
  0x1F, 0xFF, 0xF8, 0x3F, 0xFF, 0xFC, 0x7F, 0x9F, 0xFE, 0x70, 0x00, 0x7E,
  0xF0, 0x00, 0x0E, 0xFF, 0xFF, 0x07, 0xFF, 0xFF, 0xEF, 0xF8, 0x00, 0xFF,
  0xF8, 0xF0, 0x3F, 0xFF, 0xFF, 0x1F, 0xFF, 0x0F, 0xFF, 0xF8, 0x00, 0xFE,
  0x7F, 0xFC, 0x7E, 0x7F, 0xFF, 0x7E, 0x3F, 0xFF, 0xFC, 0x1F, 0xFF, 0xF8,
  0x0F, 0xFF, 0xF0, 0x07, 0xFF, 0xE0, 0x03, 0xFF, 0xC0, 0x00, 0x7E, 0x00
};

// ---------- Global State Variables ----------
char title[50]  = "";
char artist[50] = "";
char album[50]  = "";
long dur = 0, posSync = 0;
unsigned long syncAt = 0;
char state = 'N';
char prevState = ' ';
bool hasCover = false;

// Serial Line Buffer
char lineBuf[130];
byte lineIdx = 0;

// Differential Trackers
int  lastFw    = -1;
int  lastKnobX = -1;
char lastL[8]  = "";
char lastR[8]  = "";

// ---------- Helper: Format seconds to strictly 5 chars " M:SS" ----------
void fmtTime(char *buf, long s) {
  if (s < 0) s = 0;
  snprintf(buf, 6, "%2ld:%02ld", s / 60, s % 60);
}

// ---------- Print Clean Text (Wipes bounding box first) ----------
void printCleanText(int x, int y, const char *src, int maxCh, uint16_t fg, int sz) {
  int charW = 6 * sz;
  int charH = 8 * sz;

  tft.fillRect(x, y, maxCh * charW, charH, COL_BG);

  char buf[MAX_CH + 1];
  int len = strlen(src);
  if (len <= maxCh) {
    strncpy(buf, src, maxCh);
    buf[len] = 0;
  } else {
    strncpy(buf, src, maxCh - 3);
    buf[maxCh - 3] = '.';
    buf[maxCh - 2] = '.';
    buf[maxCh - 1] = '.';
    buf[maxCh] = 0;
  }

  tft.setTextSize(sz);
  tft.setTextColor(fg, COL_BG);
  tft.setCursor(x, y);
  tft.print(buf);
}

// ---------- Draw Header ----------
void drawHeader() {
  tft.fillRect(0, 0, 240, HDR_H, COL_BG);
  tft.drawBitmap(8, 2, logo24, 24, 24, COL_GREEN, COL_BG);
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(36, 7);
  tft.print(F("Spotify"));
  tft.drawFastHLine(0, HDR_H, 240, COL_BORDER);
}

// ---------- Status Badge (Top Right) ----------
void drawStatusBadge(char s) {
  tft.fillRect(150, 2, 88, 23, COL_BG);
  uint16_t col;
  const char *txt;
  if      (s == 'P') { col = COL_GREEN;   txt = "PLAYING"; }
  else if (s == 'S') { col = COL_GRAY_LT; txt = "PAUSED";  }
  else               { col = COL_GRAY_MD; txt = "STANDBY"; }

  tft.fillCircle(158, 13, 3, col);
  tft.setTextSize(1);
  tft.setTextColor(col, COL_BG);
  tft.setCursor(167, 10);
  tft.print(txt);
}

// ---------- Progress Bar Renderer (Zero Uneven Dots) ----------
void renderProgressBar(long posNow) {
  int fw = 0;
  if (dur > 0) {
    fw = (int)((long)posNow * (long)BAR_W / dur);
    if (fw > BAR_W) fw = BAR_W;
  }

  if (fw != lastFw) {
    // 1. Wipe previous knob protrusion above & below bar with BLACK
    if (lastKnobX >= 0) {
      tft.fillRect(lastKnobX - 4, BAR_Y - 3, 9, 3, COL_BG);
      tft.fillRect(lastKnobX - 4, BAR_Y + BAR_H, 9, 3, COL_BG);
    }

    // 2. Repaint green progress portion
    if (fw > 0) {
      tft.fillRoundRect(BAR_X, BAR_Y, fw, BAR_H, 2, COL_GREEN);
    }
    // 3. Repaint gray groove track
    if (fw < BAR_W) {
      tft.fillRoundRect(BAR_X + fw, BAR_Y, BAR_W - fw, BAR_H, 2, COL_TRACK);
    }

    // 4. Draw white circular knob at current position
    int knobX = BAR_X + fw;
    tft.fillCircle(knobX, BAR_Y + BAR_H / 2, 4, COL_WHITE);

    lastKnobX = knobX;
    lastFw = fw;
  }
}

// ---------- Live Progress & Seconds Update (Non-Stop, Zero Blink) ----------
void updateLiveProgress() {
  long posNow = posSync;
  if (state == 'P' && dur > 0) {
    posNow += (long)(millis() - syncAt) / 1000;
    if (posNow > dur) posNow = dur;
  }

  char nl[8];
  fmtTime(nl, posNow);

  if (strcmp(nl, lastL) != 0) {
    tft.setTextSize(2);
    tft.setTextColor(COL_WHITE, COL_BG);
    tft.setCursor(BAR_X, TIME_Y);
    tft.print(nl);
    strcpy(lastL, nl);

    renderProgressBar(posNow);
  }
}

// ---------- Streamed 200x200 Cover Image Receiver (100% Reliable) ----------
void receiveCoverImage() {
  Serial.write('K'); // ACK start command

  uint16_t rowBuf[ART_SIZE];
  uint8_t *bp = (uint8_t *)rowBuf;

  for (int row = 0; row < ART_SIZE; row++) {
    // 1. Wait for row header '#' 'L' <row_idx>
    unsigned long t0 = millis();
    while (Serial.available() < 3) {
      if (millis() - t0 > 2500) return; // Timeout abort
    }
    if (Serial.read() != '#' || Serial.read() != 'L' || Serial.read() != row) {
      return; // Sync lost
    }

    // 2. Read exactly 400 bytes in a dedicated loop (NO TFT calls here to prevent FIFO overflow!)
    int need = ART_SIZE * 2; // 400 bytes
    int got  = 0;
    t0 = millis();
    while (got < need) {
      int avail = Serial.available();
      if (avail > 0) {
        int chunk = min(avail, need - got);
        for (int i = 0; i < chunk; i++) {
          bp[got++] = Serial.read();
        }
        t0 = millis(); // Reset timeout watchdog on active progress
      } else if (millis() - t0 > 1500) {
        return; // Timeout abort
      }
    }

    // 3. Blit row to TFT GRAM
    tft.setAddrWindow(ART_X, ART_Y + row, ART_X + ART_SIZE - 1, ART_Y + row);
    tft.pushColors(rowBuf, ART_SIZE, true);

    // 4. Update the live seconds clock now (safely AFTER bytes are read!)
    updateLiveProgress();

    // 5. Send ACK 'K' to tell Python to send the next row
    Serial.write('K');
  }

  hasCover = true;
}

// ---------- Handle New Track Command ----------
void handleSong(char *payload) {
  char *p[4];
  byte k = 0;
  p[k++] = payload;
  for (char *c = payload; *c && k < 4; c++) {
    if (*c == '|') { *c = 0; p[k++] = c + 1; }
  }
  if (k < 2) return;

  strncpy(title,  p[0], 49); title[49]  = 0;
  strncpy(artist, p[1], 49); artist[49] = 0;
  if (k >= 3) { strncpy(album, p[2], 49); album[49] = 0; }
  else album[0] = 0;
  if (k >= 4) dur = atol(p[3]);

  // CRITICAL: Reset position and timer to 0 immediately!
  posSync = 0;
  syncAt = millis();
  state = 'P';
  hasCover = false;

  // Clear cover box cleanly (no flash of previous song)
  tft.fillRect(ART_X, ART_Y, ART_SIZE, ART_SIZE, COL_BG);
  tft.drawRoundRect(ART_X - 2, ART_Y - 2, ART_SIZE + 4, ART_SIZE + 4, 4, COL_BORDER);

  // Print Title & Artist
  printCleanText(TXT_X, TITLE_Y,  title,  MAX_CH, COL_WHITE,   2);
  printCleanText(TXT_X, ARTIST_Y, artist, MAX_CH, COL_GRAY_LT, 2);

  // Reset progress bar groove completely
  tft.fillRect(BAR_X - 4, BAR_Y - 4, BAR_W + 8, BAR_H + 8, COL_BG);
  tft.fillRoundRect(BAR_X, BAR_Y, BAR_W, BAR_H, 2, COL_TRACK);
  lastFw    = -1;
  lastKnobX = -1;

  // Immediately draw total duration (Right)
  char nr[8];
  if (dur > 0) fmtTime(nr, dur);
  else strcpy(nr, "--:--");
  tft.setTextSize(2);
  tft.setTextColor(COL_GRAY_LT, COL_BG);
  tft.setCursor(172, TIME_Y);
  tft.print(nr);
  strcpy(lastR, nr);

  // Immediately draw 0:00 elapsed (Left)
  char nl[8];
  fmtTime(nl, 0);
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(BAR_X, TIME_Y);
  tft.print(nl);
  strcpy(lastL, nl);
}

// ---------- Handle Live Time Update ----------
void handleTimeUpdate(char *payload) {
  char *p[3];
  byte k = 0;
  p[k++] = payload;
  for (char *c = payload; *c && k < 3; c++) {
    if (*c == ':') { *c = 0; p[k++] = c + 1; }
  }
  if (k < 3) return;

  long newPos = atol(p[0]);
  dur         = atol(p[1]);
  state       = p[2][0];

  // If a song has just started and we already ticked forward (e.g. 2, 3, or 4s)
  // while rendering cover art, do not let an accidental stale 0 snap the clock backward!
  long currentPos = posSync;
  if (state == 'P' && dur > 0) {
    currentPos += (long)(millis() - syncAt) / 1000;
  }

  if (newPos == 0 && currentPos > 1 && currentPos < 10) {
    // Ignore stale 0 right after song start: keep the clock moving!
  } else {
    posSync = newPos;
    syncAt  = millis();
  }

  if (state != prevState) {
    drawStatusBadge(state);
    prevState = state;
  }
}

// ---------- Command Dispatcher ----------
void parseCommand(char *cmd) {
  if (strncmp(cmd, "#SONG:", 6) == 0) {
    handleSong(cmd + 6);
  }
  else if (strcmp(cmd, "#IMG_START") == 0) {
    receiveCoverImage();
  }
  else if (strcmp(cmd, "#NOIMG") == 0) {
    tft.fillRect(ART_X, ART_Y, ART_SIZE, ART_SIZE, COL_SURFACE);
    tft.drawBitmap(ART_X + (ART_SIZE - 24) / 2, ART_Y + (ART_SIZE - 24) / 2, logo24, 24, 24, COL_GREEN, COL_SURFACE);
  }
  else if (strncmp(cmd, "#T:", 3) == 0) {
    handleTimeUpdate(cmd + 3);
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      lineBuf[lineIdx] = 0;
      if (lineIdx > 0) parseCommand(lineBuf);
      lineIdx = 0;
    } else if (c != '\r' && lineIdx < sizeof(lineBuf) - 1) {
      lineBuf[lineIdx++] = c;
    }
  }
}

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  tft.begin(tft.readID());
  tft.setRotation(ROTATION);

  // Triple screen clear to flush TFT controller memory
  tft.fillScreen(COL_BG); delay(30);
  tft.fillScreen(COL_BG); delay(30);
  tft.fillScreen(COL_BG);

  // Splash Screen
  tft.drawBitmap(108, 100, logo24, 24, 24, COL_GREEN, COL_BG);
  tft.setTextSize(3);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(55, 140);
  tft.print(F("Spotify"));

  tft.setTextSize(1);
  tft.setTextColor(COL_GRAY_LT, COL_BG);
  tft.setCursor(52, 185);
  tft.print(F("Connecting to laptop..."));
  delay(500);

  // Draw base shell
  tft.fillScreen(COL_BG);
  drawHeader();
  tft.drawRoundRect(ART_X - 2, ART_Y - 2, ART_SIZE + 4, ART_SIZE + 4, 4, COL_BORDER);
  tft.fillRoundRect(BAR_X, BAR_Y, BAR_W, BAR_H, 2, COL_TRACK);
  drawStatusBadge('N');
}

// ---------- Main Loop ----------
void loop() {
  static unsigned long lastUI = 0;

  readSerial();

  if (millis() - lastUI < 120) return;
  lastUI = millis();

  updateLiveProgress();
}
