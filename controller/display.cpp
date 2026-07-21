// =============================================================================
//  display.cpp — SSD1306 128×64 OLED rendering (single-page layout)
//
//  Physical screen zones (after 180° rotation):
//
//    Rows  0–46 : BLUE   — parameter grid (8 pot params; Length is in yellow)
//    Rows 47–63 : YELLOW — play state, direction, Mono/Poly, controller, length
//
//  Blue zone layout (4 rows × 2 cols):
//    Row 0 : Bas:C4     | Rng:12
//    Row 1 : Ctr:180    | Div:1/4
//    Row 2 : Wid:30     | Ply:RND
//    Row 3 : Bri:50     | Dur:16
//
//  Pot -> cell mapping (Length omitted here — shown in the yellow zone):
//    Pot 2 → Base note (Bas)     Pot 3 → Note range (Rng)
//    Pot 4 → Slice centre (Ctr)  Pot 5 → Step divider (Div)
//    Pot 6 → Slice width (Wid)   Pot 7 → Play mode (Ply)
//    Pot 8 → Slice bright (Bri)  Pot 9 → Duration Hi (Dur)
//
//  A value may be followed by a boot pick-up arrow (only until a restored pot
//  is dialled through its stored value; blank during normal operation):
//    > = pot below stored — turn right (clockwise)
//    < = pot above stored — turn left  (anti-clockwise)
//    (space) = picked up, value is live
//
//  Yellow zone layout:
//    Row 47 : separator line
//    Row 49 : "CTRL:N" (left) | play/stop icon (centre) | "LEN:NN" (right)
//    Row 57 : direction icon + "MONO"/"POLY", centred
//
//  Note: The display is rotated 180° (setRotation(2)), so row 0 is the
//  physical top after inversion, and the yellow strip sits at the bottom.
// =============================================================================

#include <Arduino.h>
#include "display.h"
#include "config.h"

// ---------------------------------------------------------------------------
//  arrow_char()
//  Returns '>' if pot is below stored (turn right), '<' if above, ' ' if
//  picked up. Picked-up check takes priority.
// ---------------------------------------------------------------------------
static char arrow_char(float pot_pos, float stored, bool picked_up) {
    if (picked_up)        return ' ';
    if (pot_pos < stored) return '>';
    if (pot_pos > stored) return '<';
    return ' ';
}

// ---------------------------------------------------------------------------
//  midi_note_name()
//  Converts a MIDI note number (0–127) to a note-name string, e.g.:
//    0  → "C-1"   60 → "C4"   69 → "A4"   127 → "G9"
//  Uses sharps throughout. Result written into buf (must be ≥ 5 bytes).
// ---------------------------------------------------------------------------
static void midi_note_name(uint8_t note, char* buf, uint8_t buf_len) {
    static const char* names[] = {
        "C","C#","D","D#","E","F","F#","G","G#","A","A#","B"
    };
    int octave = (int)(note / 12) - 1;   // MIDI octave: note 0 = C-1
    snprintf(buf, buf_len, "%s%d", names[note % 12], octave);
}

// play mode names (0–7)
static const char* play_mode_name(uint8_t m) {
    switch (m) {
        case 0: return "RND";
        case 1: return "HI";
        case 2: return "LO";
        case 3: return "MID";
        case 4: return "FST";
        case 5: return "LST";
        case 6: return "BRI";
        case 7: return "DIM";
        default: return "?";
    }
}

// Step divider label strings (indices 0–12)
static const char* step_div_name(uint8_t idx) {
    static const char* names[] = {
        "1/32","1/24","1/16","1/12","1/8","1/6",
        "1/4","1/3","1/2","1","2","3","4"
    };
    if (idx <= 12) return names[idx];
    return "?";
}

// ---------------------------------------------------------------------------
//  Grid geometry constants
//
//  Blue zone: rows 0–44 (45px), 2px spare before separator at row 47.
//    y= 0 : top border          y= 2 : text row 0 baseline
//    y=11 : H-divider            y=13 : text row 1 baseline
//    y=22 : H-divider            y=24 : text row 2 baseline
//    y=33 : H-divider            y=35 : text row 3 baseline
//    y=44 : bottom border        x=63 : vertical divider (y=0–44)
//  Left cell text starts at x=2; right cell text starts at x=65.
// ---------------------------------------------------------------------------
static const uint8_t GRID_TOP  = 0;
static const uint8_t GRID_BOT  = 44;
static const uint8_t GRID_VCOL = 63;
static const uint8_t TEXT_Y[4] = { 2, 13, 24, 35 };
static const uint8_t TEXT_X_L  = 2;
static const uint8_t TEXT_X_R  = 65;

static void draw_grid(Adafruit_SSD1306& disp) {
    disp.drawRect(0, GRID_TOP, 128, GRID_BOT - GRID_TOP + 1, SSD1306_WHITE);
    disp.drawFastHLine(0, 11, 128, SSD1306_WHITE);
    disp.drawFastHLine(0, 22, 128, SSD1306_WHITE);
    disp.drawFastHLine(0, 33, 128, SSD1306_WHITE);
    disp.drawFastVLine(GRID_VCOL, GRID_TOP, GRID_BOT - GRID_TOP + 1, SSD1306_WHITE);
}

// ---------------------------------------------------------------------------
//  display_init()
// ---------------------------------------------------------------------------
void display_init(Adafruit_SSD1306& disp) {
    if (!disp.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR)) {
        Serial.println(F("display_init: SSD1306 not found."));
        Serial.println(F("Check wiring and OLED_I2C_ADDR in config.h (0x3C or 0x3D)."));
        return;
    }

    disp.setRotation(2);
    disp.clearDisplay();
    disp.setTextSize(1);
    disp.setTextColor(SSD1306_WHITE);

    disp.setCursor(0, 0);
    disp.print(F("Seedquencer"));
    disp.setCursor(0, 12);
    disp.print(F("Controller v5"));
    disp.drawFastHLine(0, 47, 128, SSD1306_WHITE);
    disp.setCursor(0, 49);
    disp.print(F("Unit: "));
    disp.print(CONTROLLER_ID);
    disp.setCursor(0, 57);
    disp.print(F("Initialising..."));
    disp.display();
    delay(1000);
}

// ---------------------------------------------------------------------------
//  draw_params() — the single parameter grid (8 pot params; Length in yellow)
//
//  Cell layout and pot index (0-based) used for the pick-up arrow:
//    Row 0 : Bas (idx1) | Rng (idx2)
//    Row 1 : Ctr (idx3) | Div (idx4)
//    Row 2 : Wid (idx5) | Ply (idx6)
//    Row 3 : Bri (idx7) | Dur (idx8)
// ---------------------------------------------------------------------------
static void draw_params(Adafruit_SSD1306& disp, const ControllerState& s) {
    char buf[12];
    char note[5];
    char a;

    // --- Row 0: Base note (left) | Note range (right) ---
    midi_note_name(s.base_note, note, sizeof(note));
    a = arrow_char(s.pot_mapped[1], (float)s.base_note, s.pot_picked_up[1]);
    snprintf(buf, sizeof(buf), "Bas:%-3s%c", note, a);
    disp.setCursor(TEXT_X_L, TEXT_Y[0]); disp.print(buf);

    a = arrow_char(s.pot_mapped[2], (float)s.note_range, s.pot_picked_up[2]);
    snprintf(buf, sizeof(buf), "Rng:%-3d%c", s.note_range, a);
    disp.setCursor(TEXT_X_R, TEXT_Y[0]); disp.print(buf);

    // --- Row 1: Slice centre (left) | Step divider (right) ---
    a = arrow_char(s.pot_mapped[3], (float)s.slice_centre, s.pot_picked_up[3]);
    snprintf(buf, sizeof(buf), "Ctr:%-3u%c", s.slice_centre, a);
    disp.setCursor(TEXT_X_L, TEXT_Y[1]); disp.print(buf);

    a = arrow_char(s.pot_mapped[4], (float)s.step_divider, s.pot_picked_up[4]);
    snprintf(buf, sizeof(buf), "Div:%-4s%c", step_div_name(s.step_divider), a);
    disp.setCursor(TEXT_X_R, TEXT_Y[1]); disp.print(buf);

    // --- Row 2: Slice width (left) | Play mode (right) ---
    a = arrow_char(s.pot_mapped[5], (float)s.slice_width, s.pot_picked_up[5]);
    snprintf(buf, sizeof(buf), "Wid:%-3u%c", s.slice_width, a);
    disp.setCursor(TEXT_X_L, TEXT_Y[2]); disp.print(buf);

    a = arrow_char(s.pot_mapped[6], (float)s.play_mode, s.pot_picked_up[6]);
    snprintf(buf, sizeof(buf), "Ply:%-3s%c", play_mode_name(s.play_mode), a);
    disp.setCursor(TEXT_X_R, TEXT_Y[2]); disp.print(buf);

    // --- Row 3: Slice brightness (left) | Duration Hi (right) ---
    a = arrow_char(s.pot_mapped[7], (float)s.slice_bright, s.pot_picked_up[7]);
    snprintf(buf, sizeof(buf), "Bri:%-3u%c", s.slice_bright, a);
    disp.setCursor(TEXT_X_L, TEXT_Y[3]); disp.print(buf);

    a = arrow_char(s.pot_mapped[8], (float)s.dur_hi, s.pot_picked_up[8]);
    snprintf(buf, sizeof(buf), "Dur:%-2d%c", s.dur_hi, a);
    disp.setCursor(TEXT_X_R, TEXT_Y[3]); disp.print(buf);
}

// ---------------------------------------------------------------------------
//  draw_yellow_zone()
//  Rows 47–63 status bar.
//
//  Row 47: separator line
//  Row 49: "CTRL:N" (left) | play/stop icon (centre) | "LEN:NN" (right)
//  Row 57: direction icon + "MONO"/"POLY", centred as a group
//
//  Play/stop icon: filled triangle (playing) or filled square (stopped/muted),
//    reflecting tx_mode (SPDT1).
//  Direction icon: left-pointing triangle (reverse) or right-pointing triangle
//    (forward), reflecting play_direction (button).
//  MONO/POLY reflects spdt2_poly (raw SPDT2), shown even when stopped.
// ---------------------------------------------------------------------------
static void draw_yellow_zone(Adafruit_SSD1306& disp, const ControllerState& state) {
    char buf[10];

    disp.drawFastHLine(0, 47, 128, SSD1306_WHITE);

    // --- Row 49: CTRL:N (left), play/stop icon (centre), LEN:NN (right) ---
    disp.setCursor(0, 49);
    snprintf(buf, sizeof(buf), "CTRL:%d", state.controller_id);
    disp.print(buf);

    disp.setCursor(92, 49);
    snprintf(buf, sizeof(buf), "LEN:%-2d", state.length);
    disp.print(buf);

    // Play/stop icon: 8x8 region centred on x=64, top at y=49.
    if (state.tx_mode == MODE_STOPPED) {
        disp.fillRect(61, 50, 6, 6, SSD1306_WHITE);           // stop square
    } else {
        disp.fillTriangle(60, 49, 60, 55, 66, 52, SSD1306_WHITE); // play triangle
    }

    // --- Row 57: direction icon + MONO/POLY, centred as a group ---
    // Group is: [dir triangle 7px][2px gap][MONO/POLY 24px] = 33px, centre it.
    // Left edge = 64 - 33/2 ≈ 47.
    const uint8_t gx = 47;    // group left edge
    const uint8_t iy = 57;    // icon/text top

    if (state.play_direction) {
        // Forward: right-pointing triangle
        disp.fillTriangle(gx, iy, gx, iy + 6, gx + 6, iy + 3, SSD1306_WHITE);
    } else {
        // Reverse: left-pointing triangle
        disp.fillTriangle(gx + 6, iy, gx + 6, iy + 6, gx, iy + 3, SSD1306_WHITE);
    }

    disp.setCursor(gx + 9, iy);
    disp.print(state.spdt2_poly ? F("POLY") : F("MONO"));
}

// ---------------------------------------------------------------------------
//  display_update()
// ---------------------------------------------------------------------------
void display_update(Adafruit_SSD1306& disp, const ControllerState& state) {
    disp.clearDisplay();
    disp.setTextSize(1);
    disp.setTextColor(SSD1306_WHITE);

    // BLUE ZONE (rows 0–44) — grid + parameters
    draw_grid(disp);
    draw_params(disp, state);

    // YELLOW ZONE (rows 47–63)
    draw_yellow_zone(disp, state);

    disp.display();
}
