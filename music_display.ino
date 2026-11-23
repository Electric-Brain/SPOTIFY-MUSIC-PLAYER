// ============================================================================
//   SPOTIFY NOW PLAYING - ULTIMATE DEDICATED DISPLAY (PORTRAIT 240x320)
//   Hardware: Arduino UNO + MCUFRIEND 2.4" / 2.8" / 3.5" TFT Shield
// ============================================================================
// Features:
//   - Pure dedicated Spotify display with 100% space efficiency.
//   - Massive 200x200 Album Cover Art (Full screen width utilization).
//   - High-Precision Sharp Spotify Vector Logo Header.
//   - Instant Mid-Stream Cancellation (#A) on song skip (<80ms).
//   - Smooth Zero-Blink Live Seconds Counter & Lowered Scrubber Knob.
//   - Standby Clock Mode: Minimalist Digital Clock when paused or closed.
//   - Instant Wake-Up the moment Spotify plays music.
//   - Frozen timer when paused (zero phantom increments).
// ============================================================================

#include <Adafruit_GFX.h>
#include <MCUFRIEND_kbv.h>

MCUFRIEND_kbv tft;

// ---------- Screen Rotation ----------
#define ROTATION 0 // 0 = Portrait (USB at bottom)

// ---------- Spotify Colors (RGB565) ----------
#define COL_BG          0x0000  // Pure black background
#define COL_SURFACE     0x1082  // #121212 dark surface
#define COL_CARD        0x18C3  // #181818 card fill
#define COL_BORDER      0x2945  // #282828 subtle borders
#define COL_GREEN       0x1EAC  // #1ED760 Spotify green
#define COL_WHITE       0xFFFF  // Primary text / scrubber knob
#define COL_GRAY_LT     0xB576  // #B3B3B3 secondary text / duration
#define COL_GRAY_MD     0x7BEF  // #7A7A7A dim labels
#define COL_TRACK       0x39E7  // #3E3E3E progress groove

// ---------- Layout Dimensions (Portrait 240x320) ----------
#define HDR_H           28
#define ART_SIZE        200     // 200x200 Cover Art (Maximized width)
#define ART_X           20      // Centered: 20px margin left/right
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

// ---------- Sharp 24x24 Chrome Logo Bitmap (PROGMEM) ----------
const unsigned char PROGMEM logoChrome24[] = {
  0x00, 0x00, 0x00, 0x00, 0x7E, 0x00, 0x01, 0xFF, 0x80, 0x07, 0xFF, 0xE0,
  0x0F, 0xFF, 0xF0, 0x1F, 0xFF, 0xF8, 0x07, 0xFF, 0xF8, 0x3B, 0xC0, 0x00,
  0x3C, 0x81, 0xFC, 0x7F, 0x18, 0xFE, 0x7E, 0x3C, 0x7E, 0x7E, 0x7E, 0x7E,
  0x7E, 0x7E, 0x7E, 0x7E, 0x3C, 0x7E, 0x7F, 0x18, 0xFE, 0x3F, 0x81, 0xFC,
  0x3F, 0xC3, 0xFC, 0x1F, 0xF7, 0xF8, 0x1F, 0xEF, 0xF8, 0x0F, 0xEF, 0xF0,
  0x07, 0xDF, 0xE0, 0x01, 0xDF, 0x80, 0x00, 0x3E, 0x00, 0x00, 0x00, 0x00
};

// ---------- Display Modes ----------
enum DisplayMode {
  MODE_BOOT,
  MODE_WAIT_PC,
  MODE_MUSIC,
  MODE_CLOCK
};
DisplayMode currentMode = MODE_BOOT;

// ---------- Global Music Player State ----------
char title[50]  = "";
char artist[50] = "";
char album[50]  = "";
long dur = 0, posSync = 0;
unsigned long syncAt = 0;
char state = 'N';          // 'P' = playing, 'S' = paused, 'N' = standby
char prevState = ' ';
bool hasCover = false;

// Serial Line Buffer (expanded to 280 to receive full phone messages without dropping)
char lineBuf[280];
int  lineIdx = 0;

// Differential Trackers
int  lastFw    = -1;
int  lastKnobX = -1;
char lastL[8]  = "";
char lastR[8]  = "";

// Clock & System Dashboard Dimensions (Portrait 240x320)
#define CLK_START_X      6
#define CLK_TIME_Y       18
#define CLK_AMPM_Y       32
#define CLK_DATE_Y       52
#define CLK_DIV1_Y       72

#define SYS_BATT_Y       80
#define SYS_WIFI_Y       108
#define SYS_BT_Y         136
#define CLK_DIV2_Y       162

#define SYS_VOL_Y        172
#define SYS_VOL_BAR_Y    194
#define CLK_DIV3_Y       212

#define NOTIF_CARD_Y     166
#define NOTIF_CARD_H     146

char lastClockDigits[9] = "";
char lastClockAmpm[6]   = "";
char lastClockDate[32]  = "";

int  lastBatt           = -1;
int  lastChg            = -1;
char lastWifi[20]       = "";
char lastBt[20]         = "";

int  lastVolDisp        = -1;
int  lastMuteState      = -1;
bool volLabelDrawn      = false;
int  lastSentVol        = -1;

#define POT_PIN         A5
void drawVolumeWidget(int vol);
void checkVolumePot();
void clearWaterCard();
void updateWaterAnimation();

bool          notifActive   = false;
unsigned long notifExpireAt = 0;

// Autonomous Precision Clock Variables
bool          clockSynced   = false;
int           clkHour       = 0;
int           clkMin        = 0;
int           clkSec        = 0;
unsigned long clkLastTick   = 0;

// ═══════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════

void fmtTime(char *buf, long s) {
  if (s < 0) s = 0;
  long m = s / 60;
  long sec = s % 60;
  if (m >= 10) {
    buf[0] = '0' + (m / 10);
    buf[1] = '0' + (m % 10);
  } else {
    buf[0] = ' ';
    buf[1] = '0' + m;
  }
  buf[2] = ':';
  buf[3] = '0' + (sec / 10);
  buf[4] = '0' + (sec % 10);
  buf[5] = 0;
}

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

char currentAppSource = ' ';

void drawHeader(char appCode = 'S') {
  currentAppSource = appCode;
  tft.fillRect(0, 0, 240, HDR_H, COL_BG);
  if (appCode == 'C') {
    tft.drawBitmap(8, 2, logoChrome24, 24, 24, 0xFFE0, COL_BG);
  } else {
    tft.drawBitmap(8, 2, logo24, 24, 24, COL_GREEN, COL_BG);
  }
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(36, 7);
  if (appCode == 'C') {
    tft.print(F("Chrome"));
  } else if (appCode == 'M') {
    tft.print(F("Media"));
  } else {
    tft.print(F("Spotify"));
  }
  tft.drawFastHLine(0, HDR_H, 240, COL_BORDER);
}

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

// ═══════════════════════════════════════════════════════════════════
//  PROGRESS BAR & LIVE SECONDS
// ═══════════════════════════════════════════════════════════════════

void renderProgressBar(long posNow) {
  int fw = 0;
  if (dur > 0) {
    fw = (int)((long)posNow * (long)BAR_W / dur);
    if (fw > BAR_W) fw = BAR_W;
  }

  if (fw != lastFw) {
    if (lastKnobX >= 0) {
      tft.fillRect(lastKnobX - 4, BAR_Y - 3, 9, 3, COL_BG);
      tft.fillRect(lastKnobX - 4, BAR_Y + BAR_H, 9, 3, COL_BG);
    }
    if (fw > 0) {
      tft.fillRoundRect(BAR_X, BAR_Y, fw, BAR_H, 2, COL_GREEN);
    }
    if (fw < BAR_W) {
      tft.fillRoundRect(BAR_X + fw, BAR_Y, BAR_W - fw, BAR_H, 2, COL_TRACK);
    }
    int knobX = BAR_X + fw;
    tft.fillCircle(knobX, BAR_Y + BAR_H / 2, 4, COL_WHITE);
    lastKnobX = knobX;
    lastFw = fw;
  }
}

void updateLiveProgress() {
  if (currentMode != MODE_MUSIC) return;

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

// ═══════════════════════════════════════════════════════════════════
//  STANDBY CLOCK (PORTRAIT 240x320)
// ═══════════════════════════════════════════════════════════════════

void setupClockLayout() {
  tft.fillScreen(COL_BG);
  tft.setTextWrap(false);
  currentMode = MODE_CLOCK;

  memset(lastClockDigits, 0, sizeof(lastClockDigits));
  memset(lastClockAmpm,   0, sizeof(lastClockAmpm));
  memset(lastClockDate,   0, sizeof(lastClockDate));

  lastBatt = -1;
  lastChg  = -1;
  memset(lastWifi, 0, sizeof(lastWifi));
  memset(lastBt,   0, sizeof(lastBt));
  notifActive = false;

  lastVolDisp   = -1;
  lastMuteState = -1;
  volLabelDrawn = false;

  // Sleek subtle horizontal dividers
  tft.drawFastHLine(10, CLK_DIV1_Y, 220, COL_BORDER);
  tft.drawFastHLine(10, CLK_DIV2_Y, 220, COL_BORDER);
  tft.drawFastHLine(10, CLK_DIV3_Y, 220, COL_BORDER);

  if (lastSentVol >= 0) {
    drawVolumeWidget(lastSentVol);
  }
}

void renderClockDigits(const char *curDigits) {
  tft.setTextWrap(false);
  tft.setTextSize(4);
  tft.setTextColor(COL_WHITE, COL_BG);
  for (int i = 0; i < 8; i++) {
    char c = curDigits[i];
    if (c != lastClockDigits[i]) {
      tft.setCursor(CLK_START_X + i * 24, CLK_TIME_Y);
      tft.print(c);
      lastClockDigits[i] = c;
    }
  }
  lastClockDigits[8] = 0;
}

void renderClock(const char *tStr, const char *ampm, const char *dStr) {
  if (currentMode == MODE_WAIT_PC) {
    return;
  }
  if (currentMode != MODE_CLOCK) {
    setupClockLayout();
  }

  // Ensure 8-character fixed format: e.g. " 6:44:24" or "12:44:24"
  char curDigits[9];
  int rawLen = strlen(tStr);
  if (rawLen == 7) {
    curDigits[0] = ' ';
    strncpy(curDigits + 1, tStr, 7);
    curDigits[8] = 0;
  } else {
    strncpy(curDigits, tStr, 8);
    curDigits[8] = 0;
  }

  // ZERO-BLINK PER-CHARACTER UPDATE: Only redraw characters that actually changed!
  renderClockDigits(curDigits);

  // AM / PM (TextSize 2, baseline aligned, drawn ONLY when AM/PM changes)
  if (strcmp(ampm, lastClockAmpm) != 0) {
    tft.setTextSize(2);
    tft.setTextColor(COL_WHITE, COL_BG);
    tft.setCursor(CLK_START_X + 8 * 24 + 4, CLK_AMPM_Y);
    tft.print(ampm);
    strncpy(lastClockAmpm, ampm, sizeof(lastClockAmpm) - 1);
    lastClockAmpm[sizeof(lastClockAmpm) - 1] = 0;
  }

  // Date (Centered TextSize 2, drawn ONLY when date changes at midnight)
  if (strcmp(dStr, lastClockDate) != 0) {
    int dLen = strlen(dStr);
    int dateX = (240 - dLen * 12) / 2;
    if (dateX < 6) dateX = 6;

    tft.fillRect(0, CLK_DATE_Y - 2, 240, 20, COL_BG);
    tft.setTextSize(2);
    tft.setTextColor(COL_GRAY_LT, COL_BG);
    tft.setCursor(dateX, CLK_DATE_Y);
    tft.print(dStr);

    strncpy(lastClockDate, dStr, sizeof(lastClockDate) - 1);
    lastClockDate[sizeof(lastClockDate) - 1] = 0;
  }
}

// ═══════════════════════════════════════════════════════════════════
//  CLOCK MODE SYSTEM WIDGETS (BATTERY, WIFI, BLUETOOTH, NOTIFICATIONS)
// ═══════════════════════════════════════════════════════════════════

void drawBatteryWidget(int x, int y, int pct, bool chg) {
  tft.fillRect(x, y - 2, 215, 20, COL_BG);

  // 1. Battery outline (26x14) & terminal (3x6)
  tft.drawRoundRect(x, y, 26, 14, 2, COL_WHITE);
  tft.fillRect(x + 26, y + 4, 3, 6, COL_WHITE);

  // 2. Proportional battery fill
  int w = (pct * 20) / 100;
  if (w > 20) w = 20;
  if (w < 2 && pct > 0) w = 2;
  uint16_t barCol = (pct <= 20) ? 0xF800 : (pct <= 50 ? 0xFD20 : COL_GREEN);
  if (w > 0) {
    tft.fillRect(x + 3, y + 3, w, 8, barCol);
  }

  // 3. Lightning bolt ⚡ symbol if charging
  int textStartX = x + 36;
  if (chg) {
    int lx = x + 33;
    int ly = y;
    tft.drawLine(lx + 4, ly,     lx + 1, ly + 6,  0xFFE0);
    tft.drawLine(lx + 5, ly,     lx + 2, ly + 6,  0xFFE0);
    tft.drawLine(lx + 1, ly + 6, lx + 6, ly + 6,  0xFFE0);
    tft.drawLine(lx + 6, ly + 6, lx + 2, ly + 14, 0xFFE0);
    tft.drawLine(lx + 5, ly + 6, lx + 1, ly + 14, 0xFFE0);
    textStartX += 16;
  }

  // 4. Percentage & status text
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(textStartX, y);
  tft.print(pct);
  tft.print(F("%"));
  if (chg) {
    tft.setTextSize(1);
    tft.setTextColor(0xFFE0, COL_BG);
    tft.setCursor(textStartX + (pct == 100 ? 54 : 42), y + 4);
    tft.print(F("Charging"));
  }
}

void drawWifiWidget(int x, int y, const char *ssid) {
  tft.fillRect(x, y - 2, 215, 20, COL_BG);

  bool isOff  = (strcmp(ssid, "Off") == 0);
  bool isOn   = (strcmp(ssid, "On") == 0);
  bool isConn = (!isOff && !isOn && strlen(ssid) > 0);
  uint16_t col = isConn ? COL_GREEN : (isOn ? COL_GRAY_LT : COL_GRAY_MD);

  // Wi-Fi signal arcs
  tft.fillCircle(x + 8, y + 13, 2, col);
  tft.drawCircle(x + 8, y + 13, 6, col);
  tft.drawCircle(x + 8, y + 13, 10, col);
  tft.fillRect(x - 2, y + 14, 22, 8, COL_BG);

  // SSID text
  tft.setTextSize(2);
  tft.setTextColor(isConn ? COL_WHITE : col, COL_BG);
  tft.setCursor(x + 26, y);
  char buf[17];
  strncpy(buf, ssid, 16);
  buf[16] = 0;
  tft.print(buf);
}

void drawBtWidget(int x, int y, const char *device) {
  tft.fillRect(x, y - 2, 215, 20, COL_BG);

  bool isOff  = (strcmp(device, "Off") == 0);
  bool isOn   = (strcmp(device, "On") == 0);
  bool isConn = (!isOff && !isOn && strlen(device) > 0 && strcmp(device, "None") != 0);
  uint16_t col = isConn ? 0x051F : (isOn ? COL_GRAY_LT : COL_GRAY_MD);

  // Bluetooth ᛒ symbol
  tft.drawFastVLine(x + 6, y, 15, col);
  tft.drawFastVLine(x + 7, y, 15, col);
  tft.drawLine(x + 2, y + 3,  x + 11, y + 11, col);
  tft.drawLine(x + 11, y + 11, x + 6, y + 15, col);
  tft.drawLine(x + 2, y + 12, x + 11, y + 4,  col);
  tft.drawLine(x + 11, y + 4,  x + 6, y,      col);

  // Device Name text
  tft.setTextSize(2);
  tft.setTextColor(isConn ? COL_WHITE : col, COL_BG);
  tft.setCursor(x + 26, y);
  char buf[17];
  strncpy(buf, (isOff || isOn || isConn) ? device : "Off", 16);
  buf[16] = 0;
  tft.print(buf);
}

void drawNotificationCard(const char *app, const char *msg) {
  // Clear card area
  tft.fillRect(8, NOTIF_CARD_Y, 224, NOTIF_CARD_H + 2, COL_BG);

  // Card background & vibrant green border
  tft.fillRoundRect(8, NOTIF_CARD_Y, 224, NOTIF_CARD_H, 6, COL_CARD);
  tft.drawRoundRect(8, NOTIF_CARD_Y, 224, NOTIF_CARD_H, 6, COL_GREEN);

  // Subtle header divider inside card
  tft.drawFastHLine(14, NOTIF_CARD_Y + 25, 212, COL_BORDER);

  // Bell icon in yellow
  uint16_t bellCol = 0xFFE0;
  tft.fillRoundRect(18, NOTIF_CARD_Y + 9, 8, 8, 2, bellCol);
  tft.drawFastHLine(16, NOTIF_CARD_Y + 17, 12, bellCol);
  tft.drawPixel(21, NOTIF_CARD_Y + 7, bellCol);
  tft.drawPixel(21, NOTIF_CARD_Y + 19, bellCol);

  // App / Sender Title (TextSize 2, bold white)
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_CARD);
  tft.setCursor(34, NOTIF_CARD_Y + 7);
  char appBuf[16];
  strncpy(appBuf, app, 15);
  appBuf[15] = 0;
  tft.print(appBuf);

  // Notification message with clean word-wrapping across up to 10 lines
  tft.setTextSize(1);
  tft.setTextColor(COL_WHITE, COL_CARD);

  int lineX = 14;
  int lineY = NOTIF_CARD_Y + 30;
  int maxCharsPerLine = 35;
  int lineCount = 0;
  int maxLines = 10;

  const char *p = msg;
  while (*p && lineCount < maxLines) {
    while (*p == ' ') p++;
    if (!*p) break;

    const char *lineStart = p;
    const char *lastBreak = NULL;
    int len = 0;

    while (*p && len < maxCharsPerLine) {
      if (*p == ' ') lastBreak = p;
      len++;
      p++;
    }

    int printLen = len;
    if (*p && len >= maxCharsPerLine) {
      if (lastBreak && lastBreak > lineStart) {
        printLen = lastBreak - lineStart;
        p = lastBreak + 1;
      } else {
        printLen = maxCharsPerLine;
      }
    }

    tft.setCursor(lineX, lineY);
    for (int i = 0; i < printLen; i++) {
      tft.write(lineStart[i]);
    }
    lineY += 11;
    lineCount++;
  }

  notifActive = true;
  notifExpireAt = millis() + 16000;
}

void clearNotificationCard() {
  if (!notifActive) return;
  tft.fillRect(8, NOTIF_CARD_Y, 224, NOTIF_CARD_H + 2, COL_BG);
  notifActive = false;

  // Restore divider and volume widget cleanly
  tft.drawFastHLine(10, CLK_DIV3_Y, 220, COL_BORDER);
  volLabelDrawn = false;
  lastMuteState = -1;
  lastVolDisp   = -1;
  if (lastSentVol >= 0) {
    drawVolumeWidget(lastSentVol);
  }
}

// ═══════════════════════════════════════════════════════════════════
//  ANIMATED KAWAII WATER REMINDER (12-SEC POP-UP EVERY 30 MIN)
// ═══════════════════════════════════════════════════════════════════

#define WATER_CARD_Y 218
#define WATER_CARD_H 94

unsigned long waterLastAlert = 0;
bool          waterActive    = false;
unsigned long waterExpireAt  = 0;
unsigned long lastBlinkTime  = 0;
bool          eyesClosed     = false;

void drawWaterDroplet(int cx, int cy, bool blink) {
  tft.fillTriangle(cx, cy - 24, cx - 14, cy, cx + 14, cy, 0x07FF);
  tft.fillCircle(cx, cy, 14, 0x07FF);
  tft.drawPixel(cx - 6, cy - 11, COL_WHITE);
  tft.drawPixel(cx - 5, cy - 12, COL_WHITE);

  tft.fillCircle(cx - 9, cy + 4, 2, 0xFA14);
  tft.fillCircle(cx + 9, cy + 4, 2, 0xFA14);

  if (blink) {
    tft.fillRect(cx - 8, cy - 2, 16, 5, 0x07FF);
    tft.drawFastHLine(cx - 6, cy, 4, COL_WHITE);
    tft.drawFastHLine(cx + 2, cy, 4, COL_WHITE);
  } else {
    tft.fillCircle(cx - 5, cy, 2, COL_WHITE);
    tft.fillCircle(cx + 5, cy, 2, COL_WHITE);
    tft.drawPixel(cx - 5, cy, COL_BG);
    tft.drawPixel(cx + 5, cy, COL_BG);
  }

  tft.drawPixel(cx - 2, cy + 6, COL_WHITE);
  tft.drawPixel(cx - 1, cy + 7, COL_WHITE);
  tft.drawPixel(cx,     cy + 7, COL_WHITE);
  tft.drawPixel(cx + 1, cy + 7, COL_WHITE);
  tft.drawPixel(cx + 2, cy + 6, COL_WHITE);
}

void drawWaterCard() {
  tft.fillRoundRect(8, WATER_CARD_Y, 224, WATER_CARD_H, 6, COL_CARD);
  tft.drawRoundRect(8, WATER_CARD_Y, 224, WATER_CARD_H, 6, 0x07FF);
  drawWaterDroplet(38, WATER_CARD_Y + 44, false);

  tft.setTextSize(2);
  tft.setTextColor(0x07FF, COL_CARD);
  tft.setCursor(66, WATER_CARD_Y + 14);
  tft.print(F("HYDRATE!"));

  tft.setTextSize(1);
  tft.setTextColor(0xFFE0, COL_CARD);
  tft.setCursor(66, WATER_CARD_Y + 38);
  tft.print(F("Time to drink water!"));

  tft.setTextColor(COL_GREEN, COL_CARD);
  tft.setCursor(66, WATER_CARD_Y + 54);
  tft.print(F("* Take a sip now! 💧 *"));

  // 12-second countdown bar
  tft.drawRoundRect(66, WATER_CARD_Y + 72, 150, 4, 2, COL_TRACK);
  tft.fillRoundRect(66, WATER_CARD_Y + 72, 150, 4, 2, 0x07FF);
}

void clearWaterCard() {
  if (!waterActive) return;
  tft.fillRect(8, WATER_CARD_Y, 224, WATER_CARD_H + 2, COL_BG);
  waterActive = false;
  waterLastAlert = millis();
}

void updateWaterAnimation() {
  if (currentMode != MODE_CLOCK) return;

  unsigned long now = millis();
  const unsigned long interval = 30UL * 60UL * 1000UL; // 30 minutes

  // Trigger pop-up every 30 minutes if no notification is showing
  if (!waterActive && !notifActive) {
    if (now - waterLastAlert >= interval) {
      waterActive   = true;
      waterExpireAt = now + 12000; // Visible for 12 seconds
      drawWaterCard();
      lastBlinkTime = now;
      eyesClosed    = false;
    }
  }

  // Active animation while pop-up is showing
  if (waterActive) {
    if (notifActive || now > waterExpireAt) {
      clearWaterCard();
      return;
    }

    // Eye blink every 2.5s
    if (!eyesClosed && (now - lastBlinkTime > 2500)) {
      drawWaterDroplet(38, WATER_CARD_Y + 44, true);
      eyesClosed = true;
      lastBlinkTime = now;
    } else if (eyesClosed && (now - lastBlinkTime > 150)) {
      drawWaterDroplet(38, WATER_CARD_Y + 44, false);
      eyesClosed = false;
      lastBlinkTime = now;
    }

    // Shrinking countdown bar
    long rem = waterExpireAt - now;
    if (rem < 0) rem = 0;
    int curW = (int)((rem * 150L) / 12000L);
    if (curW < 150) {
      tft.fillRect(66 + curW, WATER_CARD_Y + 72, 150 - curW, 4, COL_TRACK);
    }
  }
}

void drawVolumeWidget(int vol) {
  if (currentMode != MODE_CLOCK) return;

  int x = 16;
  int y = SYS_VOL_Y;

  // 1. Speaker icon (X=16, Y=SYS_VOL_Y)
  int muteState = (vol == 0) ? 0 : (vol <= 35 ? 1 : (vol <= 70 ? 2 : 3));
  if (muteState != lastMuteState) {
    tft.fillRect(x, y - 1, 24, 16, COL_BG);

    // Speaker body & cone
    tft.fillRect(x, y + 3, 4, 8, COL_WHITE);
    tft.fillTriangle(x + 4, y + 3, x + 10, y, x + 4, y + 10, COL_WHITE);
    tft.fillTriangle(x + 4, y + 10, x + 10, y + 13, x + 10, y, COL_WHITE);

    if (vol == 0) {
      // Mute red X
      tft.drawLine(x + 13, y + 3, x + 21, y + 11, 0xF800);
      tft.drawLine(x + 21, y + 3, x + 13, y + 11, 0xF800);
    } else {
      // Small sound wave
      tft.drawLine(x + 13, y + 4, x + 15, y + 7, COL_GREEN);
      tft.drawLine(x + 15, y + 7, x + 13, y + 10, COL_GREEN);
      if (vol > 35) {
        // Medium sound wave
        tft.drawLine(x + 17, y + 2, x + 20, y + 7, COL_GREEN);
        tft.drawLine(x + 20, y + 7, x + 17, y + 12, COL_GREEN);
      }
    }
    lastMuteState = muteState;
  }

  // 2. "VOLUME" Label (TextSize 2, white)
  if (!volLabelDrawn) {
    tft.setTextSize(2);
    tft.setTextColor(COL_WHITE, COL_BG);
    tft.setCursor(x + 28, y);
    tft.print(F("VOLUME"));
    volLabelDrawn = true;
  }

  // 3. Percentage Text (TextSize 2, green, e.g. " 75%")
  if (vol != lastVolDisp) {
    char vBuf[6];
    if (vol >= 100) {
      strcpy(vBuf, "100%");
    } else if (vol >= 10) {
      vBuf[0] = ' ';
      vBuf[1] = '0' + (vol / 10);
      vBuf[2] = '0' + (vol % 10);
      vBuf[3] = '%';
      vBuf[4] = 0;
    } else {
      vBuf[0] = ' ';
      vBuf[1] = ' ';
      vBuf[2] = '0' + vol;
      vBuf[3] = '%';
      vBuf[4] = 0;
    }
    tft.setTextSize(2);
    tft.setTextColor(COL_GREEN, COL_BG);
    tft.setCursor(168, y);
    tft.print(vBuf);
    lastVolDisp = vol;
  }

  // 4. Volume Bar (Y=SYS_VOL_BAR_Y, W=208, H=8, rounded corners)
  int barX = 16;
  int barY = SYS_VOL_BAR_Y;
  int barW = 208;
  int barH = 8;

  int fillW = (vol * barW) / 100;
  if (fillW < 0) fillW = 0;
  if (fillW > barW) fillW = barW;

  if (fillW > 0) {
    tft.fillRoundRect(barX, barY, fillW, barH, 3, COL_GREEN);
  }
  if (fillW < barW) {
    tft.fillRoundRect(barX + fillW, barY, barW - fillW, barH, 3, COL_TRACK);
  }
}

// ═══════════════════════════════════════════════════════════════════
//  COVER IMAGE RECEIVER (WITH FAST MID-STREAM ABORT SUPPORT)
// ═══════════════════════════════════════════════════════════════════

void receiveCoverImage() {
  Serial.write('K'); // ACK start

  uint16_t rowBuf[ART_SIZE];
  uint8_t *bp = (uint8_t *)rowBuf;

  for (int row = 0; row < ART_SIZE; row++) {
    checkVolumePot();

    unsigned long t0 = millis();
    while (Serial.available() < 3) {
      checkVolumePot();
      if (millis() - t0 > 800) return;
    }

    char c1 = Serial.read();
    char c2 = Serial.read();
    byte r  = Serial.read();

    // Check for Abort signal (#A) from PC when user switches song mid-stream
    if (c1 == '#' && c2 == 'A') {
      tft.fillRect(ART_X, ART_Y, ART_SIZE, ART_SIZE, COL_BG);
      tft.drawRoundRect(ART_X - 2, ART_Y - 2, ART_SIZE + 4, ART_SIZE + 4, 4, COL_BORDER);
      return; // Instantly exit and return to loop() to receive new song!
    }

    if (c1 != '#' || c2 != 'L' || r != row) {
      return;
    }

    int need = ART_SIZE * 2;
    int got  = 0;
    t0 = millis();
    while (got < need) {
      int avail = Serial.available();
      if (avail > 0) {
        int chunk = min(avail, need - got);
        for (int i = 0; i < chunk; i++) {
          bp[got++] = Serial.read();
        }
        t0 = millis();
      } else {
        checkVolumePot();
        if (millis() - t0 > 600) {
          return;
        }
      }
    }

    tft.setAddrWindow(ART_X, ART_Y + row, ART_X + ART_SIZE - 1, ART_Y + row);
    tft.pushColors(rowBuf, ART_SIZE, true);

    updateLiveProgress();
    checkVolumePot();
    Serial.write('K');
  }

  hasCover = true;
}

// ═══════════════════════════════════════════════════════════════════
//  COMMAND HANDLERS
// ═══════════════════════════════════════════════════════════════════

void handleSong(char *payload) {
  if (currentMode == MODE_WAIT_PC) return;

  char *p[7];
  byte k = 0;
  p[k++] = payload;
  for (char *c = payload; *c && k < 7; c++) {
    if (*c == '|') { *c = 0; p[k++] = c + 1; }
  }
  if (k < 2) return;

  char appCode = (k >= 7 && p[6][0]) ? p[6][0] : 'S';
  if (currentMode != MODE_MUSIC || currentAppSource != appCode) {
    if (currentMode != MODE_MUSIC) {
      tft.fillScreen(COL_BG);
    }
    drawHeader(appCode);
    currentMode = MODE_MUSIC;
    notifActive = false;
    clockSynced = false;
  }

  strncpy(title,  p[0], 49); title[49]  = 0;
  strncpy(artist, p[1], 49); artist[49] = 0;
  if (k >= 3) { strncpy(album, p[2], 49); album[49] = 0; }
  else album[0] = 0;
  dur = (k >= 4) ? atol(p[3]) : 0;
  posSync = (k >= 5) ? atol(p[4]) : 0;
  state = (k >= 6 && p[5][0]) ? p[5][0] : 'P';
  prevState = state;

  syncAt = millis();
  hasCover = false;

  // Clear player elements cleanly
  tft.fillRect(ART_X, ART_Y, ART_SIZE, ART_SIZE, COL_BG);
  tft.drawRoundRect(ART_X - 2, ART_Y - 2, ART_SIZE + 4, ART_SIZE + 4, 4, COL_BORDER);

  printCleanText(TXT_X, TITLE_Y,  title,  MAX_CH, COL_WHITE,   2);
  printCleanText(TXT_X, ARTIST_Y, artist, MAX_CH, COL_GRAY_LT, 2);

  tft.fillRect(BAR_X - 4, BAR_Y - 4, BAR_W + 8, BAR_H + 8, COL_BG);
  tft.fillRoundRect(BAR_X, BAR_Y, BAR_W, BAR_H, 2, COL_TRACK);
  lastFw    = -1;
  lastKnobX = -1;

  // Total Duration (Right)
  char nr[8];
  if (dur > 0) fmtTime(nr, dur);
  else strcpy(nr, "--:--");
  tft.setTextSize(2);
  tft.setTextColor(COL_GRAY_LT, COL_BG);
  tft.setCursor(172, TIME_Y);
  tft.print(nr);
  strcpy(lastR, nr);

  // Initial Elapsed Time (Left) - reflects actual position
  char nl[8];
  fmtTime(nl, posSync);
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(BAR_X, TIME_Y);
  tft.print(nl);
  strcpy(lastL, nl);

  // Initial Progress Bar & Scrubber position
  renderProgressBar(posSync);

  // Status badge ('PLAYING' or 'PAUSED')
  drawStatusBadge(state);
}

void handleTimeUpdate(char *payload) {
  if (currentMode != MODE_MUSIC) return;

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

  long currentPos = posSync;
  if (state == 'P' && dur > 0) {
    currentPos += (long)(millis() - syncAt) / 1000;
  }

  if (newPos == 0 && currentPos > 1 && currentPos < 10) {
    // Ignore stale zero right after song start
  } else {
    posSync = newPos;
    syncAt  = millis();
  }

  if (state != prevState) {
    drawStatusBadge(state);
    prevState = state;
  }

  // Update total duration text if it changed
  char nr[8];
  if (dur > 0) fmtTime(nr, dur);
  else strcpy(nr, "--:--");
  if (strcmp(nr, lastR) != 0) {
    tft.setTextSize(2);
    tft.setTextColor(COL_GRAY_LT, COL_BG);
    tft.setCursor(172, TIME_Y);
    tft.print(nr);
    strcpy(lastR, nr);
  }
}

void handleClock(char *payload) {
  // Truncate merged commands if a newline was lost during USB connect
  char *hash = strchr(payload, '#');
  if (hash) *hash = 0;

  char *p[3];
  byte k = 0;
  p[k++] = payload;
  for (char *c = payload; *c && k < 3; c++) {
    if (*c == '|') { *c = 0; p[k++] = c + 1; }
  }
  if (k < 3) return;

  // Validate time string (must be 7 or 8 chars, e.g. " 9:53:12")
  int tLen = strlen(p[0]);
  if (tLen < 7 || tLen > 8) return;

  // Validate AM/PM (must be exactly 2 chars)
  int aLen = strlen(p[1]);
  if (aLen != 2) return;

  // Validate Date string length (must be reasonable)
  int dLen = strlen(p[2]);
  if (dLen < 4 || dLen > 24) return;

  if (currentMode == MODE_WAIT_PC) {
    return;
  }

  if (currentMode != MODE_CLOCK) {
    setupClockLayout();
  }

  state = 'S'; // Stop any ongoing music counter

  // Sync internal clock components for autonomous second ticking
  char *c1 = strchr(p[0], ':');
  if (c1) {
    char *c2 = strchr(c1 + 1, ':');
    if (c2) {
      clkHour     = atoi(p[0]);
      clkMin      = atoi(c1 + 1);
      clkSec      = atoi(c2 + 1);
      clkLastTick = millis();
      clockSynced = true;
    }
  }

  renderClock(p[0], p[1], p[2]);
}

void handleSys(char *payload) {
  if (currentMode != MODE_CLOCK) return;

  char *hash = strchr(payload, '#');
  if (hash) *hash = 0;

  char *p[4];
  byte k = 0;
  p[k++] = payload;
  for (char *c = payload; *c && k < 4; c++) {
    if (*c == '|') { *c = 0; p[k++] = c + 1; }
  }
  if (k < 4) return;

  int pct = atoi(p[0]);
  int chg = atoi(p[1]);
  char *wifi = p[2];
  char *bt   = p[3];

  if (pct != lastBatt || chg != lastChg) {
    drawBatteryWidget(16, SYS_BATT_Y, pct, chg != 0);
    lastBatt = pct;
    lastChg  = chg;
  }

  if (strcmp(wifi, lastWifi) != 0) {
    drawWifiWidget(16, SYS_WIFI_Y, wifi);
    strncpy(lastWifi, wifi, sizeof(lastWifi) - 1);
    lastWifi[sizeof(lastWifi) - 1] = 0;
  }

  if (strcmp(bt, lastBt) != 0) {
    drawBtWidget(16, SYS_BT_Y, bt);
    strncpy(lastBt, bt, sizeof(lastBt) - 1);
    lastBt[sizeof(lastBt) - 1] = 0;
  }
}

void handleNotif(char *payload) {
  if (currentMode != MODE_CLOCK) return;
  if (waterActive) clearWaterCard();

  char *hash = strchr(payload, '#');
  if (hash) *hash = 0;

  char *p[2];
  byte k = 0;
  p[k++] = payload;
  for (char *c = payload; *c && k < 2; c++) {
    if (*c == '|') { *c = 0; p[k++] = c + 1; }
  }
  if (k < 2) return;

  drawNotificationCard(p[0], p[1]);
}

void handleVol(char *payload) {
  int vol = atoi(payload);
  vol = constrain(vol, 0, 100);
  lastSentVol = vol;
  if (currentMode == MODE_CLOCK) {
    drawVolumeWidget(vol);
  }
}

void parseCommand(char *cmd) {
  if (strncmp(cmd, "#SONG:", 6) == 0) {
    handleSong(cmd + 6);
  }
  else if (strcmp(cmd, "#IMG_START") == 0) {
    receiveCoverImage();
  }
  else if (strcmp(cmd, "#NOIMG") == 0) {
    tft.fillRect(ART_X, ART_Y, ART_SIZE, ART_SIZE, COL_SURFACE);
    if (currentAppSource == 'C') {
      tft.drawBitmap(ART_X + (ART_SIZE - 24) / 2, ART_Y + (ART_SIZE - 24) / 2, logoChrome24, 24, 24, 0xFFE0, COL_SURFACE);
    } else {
      tft.drawBitmap(ART_X + (ART_SIZE - 24) / 2, ART_Y + (ART_SIZE - 24) / 2, logo24, 24, 24, COL_GREEN, COL_SURFACE);
    }
  }
  else if (strncmp(cmd, "#T:", 3) == 0) {
    handleTimeUpdate(cmd + 3);
  }
  else if (strncmp(cmd, "#CLOCK:", 7) == 0) {
    handleClock(cmd + 7);
  }
  else if (strncmp(cmd, "#SYS:", 5) == 0) {
    handleSys(cmd + 5);
  }
  else if (strncmp(cmd, "#NOTIF:", 7) == 0) {
    handleNotif(cmd + 7);
  }
  else if (strncmp(cmd, "#VOL:", 5) == 0) {
    handleVol(cmd + 5);
  }
  else if (strcmp(cmd, "#LOCK") == 0) {
    if (currentMode != MODE_WAIT_PC) {
      setupWaitPcLayout();
    }
  }
  else if (strcmp(cmd, "#UNLOCK") == 0) {
    if (currentMode == MODE_WAIT_PC) {
      tft.fillScreen(COL_BG);
      tft.fillCircle(120, 105, 24, COL_GREEN);
      tft.drawLine(108, 105, 116, 113, COL_WHITE);
      tft.drawLine(109, 105, 117, 113, COL_WHITE);
      tft.drawLine(116, 113, 132, 97, COL_WHITE);
      tft.drawLine(117, 113, 133, 97, COL_WHITE);

      tft.setTextSize(2);
      tft.setTextColor(COL_WHITE, COL_BG);
      tft.setCursor(62, 148);
      tft.print(F("CONNECTED"));

      tft.setTextSize(1);
      tft.setTextColor(COL_GRAY_LT, COL_BG);
      tft.setCursor(80, 172);
      tft.print(F("SYSTEM READY"));
      delay(350);

      setupClockLayout();
    }
  }
}

// ═══════════════════════════════════════════════════════════════════
//  HARDWARE POTENTIOMETER VOLUME CONTROL (PIN A5)
// ═══════════════════════════════════════════════════════════════════

void checkVolumePot() {
  static unsigned long lastPotCheck = 0;
  static int lastSentRaw = -1;
  static float filteredAdc = -1.0;

  // Throttle ADC reads to ~30ms for responsive yet jitter-free control
  if (millis() - lastPotCheck < 30) return;
  lastPotCheck = millis();

  // Settle ADC S/H capacitor for high-impedance 47k pot (throwaway read)
  analogRead(POT_PIN);
  int sample = analogRead(POT_PIN);
  if (filteredAdc < 0) {
    // Cold boot initialization: record starting knob position without jumping volume
    filteredAdc = sample;
    lastSentRaw = sample;
    int clamped = constrain(sample, 10, 1014);
    lastSentVol = map(clamped, 10, 1014, 0, 100);
    lastSentVol = constrain(lastSentVol, 0, 100);
    return;
  }

  // Smooth ADC readings with exponential moving average (ideal for 47k pot impedance)
  filteredAdc = filteredAdc * 0.70 + sample * 0.30;
  int raw = (int)(filteredAdc + 0.5);

  // Deadband: must move by at least 10 ADC counts (~1%) to trigger (avoids resting flutter)
  if (abs(raw - lastSentRaw) >= 10) {
    lastSentRaw = raw;
    int clamped = constrain(raw, 10, 1014);
    int vol = map(clamped, 10, 1014, 0, 100);
    vol = constrain(vol, 0, 100);
    if (vol != lastSentVol) {
      Serial.print(F("#VOL:"));
      Serial.println(vol);
      lastSentVol = vol;
      if (waterActive) {
        clearWaterCard();
      }
      if (currentMode == MODE_CLOCK) {
        drawVolumeWidget(vol);
      }
    }
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      lineBuf[lineIdx] = 0;
      if (lineIdx > 0) parseCommand(lineBuf);
      lineIdx = 0;
    } else if (c != '\r') {
      if (lineIdx < sizeof(lineBuf) - 1) {
        lineBuf[lineIdx++] = c;
      } else {
        lineIdx = 0; // Drop corrupted line if buffer overflows without seeing newline
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════════
//  SETUP & MAIN LOOP
// ═══════════════════════════════════════════════════════════════════

void setupWaitPcLayout() {
  tft.fillScreen(COL_BG);
  currentMode = MODE_WAIT_PC;
  clockSynced = false;
  notifActive = false;

  // Header separator
  tft.drawFastHLine(15, 26, 210, COL_BORDER);

  // Modern Spotify Green Lock Icon
  // Arch (Shackle)
  tft.drawRoundRect(96, 52, 48, 44, 16, COL_GREEN);
  tft.drawRoundRect(97, 53, 46, 42, 15, COL_GREEN);
  tft.fillRect(98, 76, 44, 20, COL_BG);

  // Body
  tft.fillRoundRect(80, 80, 80, 60, 8, COL_CARD);
  tft.drawRoundRect(80, 80, 80, 60, 8, COL_GREEN);

  // Keyhole
  tft.fillCircle(120, 102, 6, COL_GREEN);
  tft.fillTriangle(117, 104, 123, 104, 120, 120, COL_GREEN);

  // Main Status Text
  tft.setTextSize(3);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(66, 150);
  tft.print(F("LOCKED"));

  // Secondary text
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(36, 180);
  tft.print(F("ENTER PASSWORD"));

  // Info label
  tft.setTextSize(1);
  tft.setTextColor(COL_GRAY_LT, COL_BG);
  tft.setCursor(50, 212);
  tft.print(F("Waiting for PC login..."));

  // Bottom pulsing track rail
  tft.drawRoundRect(30, 252, 180, 6, 3, COL_TRACK);
}

void updateWaitPcAnimation() {
  static unsigned long lastPulse = 0;
  static int pulseX = 35;
  static int pulseDir = 3;

  if (millis() - lastPulse < 30) return;
  lastPulse = millis();

  // Clear previous dot
  tft.fillRect(pulseX - 8, 253, 24, 4, COL_BG);
  tft.drawFastHLine(max(32, pulseX - 8), 254, min(176, 24), COL_TRACK);

  pulseX += pulseDir;
  if (pulseX >= 195) { pulseX = 195; pulseDir = -3; }
  else if (pulseX <= 45) { pulseX = 45; pulseDir = 3; }

  // Draw sleek glowing dot
  tft.fillRoundRect(pulseX - 6, 253, 12, 4, 2, COL_GREEN);
}

void playBootAnimation() {
  tft.fillScreen(COL_BG);

  // ── 1. Sleek Minimalist Laptop (Apple / Google hardware aesthetic) ──
  tft.drawRoundRect(88, 72, 64, 42, 3, COL_WHITE);
  tft.fillRoundRect(90, 74, 60, 38, 2, COL_SURFACE);
  tft.fillCircle(120, 76, 1, COL_GREEN);        // ambient camera dot
  tft.fillRect(78, 114, 84, 4, COL_WHITE);       // unibody base
  tft.fillRect(112, 114, 16, 2, COL_SURFACE);    // trackpad groove
  delay(180);

  // ── 2. Clean Typography ──
  tft.setTextSize(2);
  tft.setTextColor(COL_WHITE, COL_BG);
  tft.setCursor(62, 142);
  tft.print(F("SMART DECK"));

  tft.setTextSize(1);
  tft.setTextColor(COL_GRAY_MD, COL_BG);
  tft.setCursor(76, 168);
  tft.print(F("DESK COMPANION"));

  // ── 3. Smooth macOS-style minimal progress bar ──
  tft.drawRoundRect(45, 196, 150, 4, 2, COL_TRACK);
  for (int w = 0; w <= 146; w += 4) {
    tft.fillRoundRect(47, 197, w, 2, 1, COL_WHITE);
    delay(16);
  }

  delay(350);
}

void setup() {
  Serial.begin(115200);

  tft.begin(tft.readID());
  tft.setRotation(ROTATION);

  // Begin display and play sleek intro animation
  playBootAnimation();

  // Read volume pot starting position
  checkVolumePot();

  // Start in Locked / Waiting PC mode by default until Windows logs in & unlocks
  setupWaitPcLayout();

  // Flush any stale/corrupted bytes that arrived during bootloader & splash delays
  while (Serial.available()) Serial.read();
  lineIdx = 0;

  // Send ready handshake so Python knows Arduino is alive
  Serial.println(F("#READY"));
}

void loop() {
  static unsigned long lastUI = 0;

  readSerial();
  checkVolumePot();

  if (currentMode == MODE_WAIT_PC) {
    updateWaitPcAnimation();
    return;
  }

  if (currentMode == MODE_CLOCK) {
    if (notifActive && millis() > notifExpireAt) {
      clearNotificationCard();
    }
    updateWaterAnimation();

    // Autonomous precision quartz ticker: advances seconds every 1000ms live
    if (clockSynced && (millis() - clkLastTick >= 1000)) {
      clkLastTick += 1000;
      clkSec++;
      if (clkSec >= 60) {
        clkSec = 0;
        clkMin++;
        if (clkMin >= 60) {
          clkMin = 0;
          clkHour++;
          if (clkHour == 12) {
            if (strcmp(lastClockAmpm, "AM") == 0) strcpy(lastClockAmpm, "PM");
            else strcpy(lastClockAmpm, "AM");
            tft.setTextSize(2);
            tft.setTextColor(COL_WHITE, COL_BG);
            tft.setCursor(CLK_START_X + 8 * 24 + 4, CLK_AMPM_Y);
            tft.print(lastClockAmpm);
          } else if (clkHour > 12) {
            clkHour = 1;
          }
        }
      }
      char tBuf[9];
      if (clkHour < 10) {
        tBuf[0] = ' ';
        tBuf[1] = '0' + clkHour;
      } else {
        tBuf[0] = '0' + (clkHour / 10);
        tBuf[1] = '0' + (clkHour % 10);
      }
      tBuf[2] = ':';
      tBuf[3] = '0' + (clkMin / 10);
      tBuf[4] = '0' + (clkMin % 10);
      tBuf[5] = ':';
      tBuf[6] = '0' + (clkSec / 10);
      tBuf[7] = '0' + (clkSec % 10);
      tBuf[8] = 0;
      renderClockDigits(tBuf);
    }
  }

  if (millis() - lastUI < 120) return;
  lastUI = millis();

  updateLiveProgress();
}