// =============================================================================
//  inputs.cpp — Pot reading, switch reading, direction-toggle button handling
//
//    Pot 1 (idx 0) → length          Pot 2 (idx 1) → base_note
//    Pot 3 (idx 2) → note_range       Pot 4 (idx 3) → slice_centre
//    Pot 5 (idx 4) → step_divider     Pot 6 (idx 5) → slice_width
//    Pot 7 (idx 6) → play_mode        Pot 8 (idx 7) → slice_bright
//    Pot 9 (idx 8) → dur_hi (mapped across 1..current length)
//
//  Parameters NOT driven by a pot are held at fixed firmware defaults and are
//  transmitted in every payload:
//    vel_lo = DEFAULT_VEL_LO   vel_hi = DEFAULT_VEL_HI   dur_lo = DEFAULT_DUR_LO
//    param_mode = DEFAULT_PARAM_MODE   midi_channel = controller_id (1..16)
//
//  Momentary button (PIN_BTN_DIR): toggles play_direction on debounced release.
//
//  SPDT1 (PIN_SPDT1, active HIGH): Mute/Stop — overrides tx_mode to 0.
//  SPDT2 (PIN_SPDT2, active LOW): Mono/Poly — tx_mode = 1 (mono) or 2 (poly).
// =============================================================================

#include <Arduino.h>
#include "inputs.h"
#include "config.h"
#include "state.h"

// ---------------------------------------------------------------------------
//  Helpers
// ---------------------------------------------------------------------------
static int map_adc_int(float raw, int out_min, int out_max) {
    return (int)(out_min + (raw / 4095.0f) * (float)(out_max - out_min) + 0.5f);
}

static float iir_update(float& stored, float raw) {
    if (stored < 0.0f) { stored = raw; }
    else               { stored = stored * (1.0f - POT_IIR_ALPHA) + raw * POT_IIR_ALPHA; }
    return stored;
}

// ---------------------------------------------------------------------------
//  Pickup confirm counters (one per pot)
// ---------------------------------------------------------------------------
static uint8_t pickup_confirm[9] = {0};

// check_pickup: returns true once pot has been within 'tolerance' of 'stored'
// for PICKUP_CONFIRM_CYCLES consecutive scans. 'blocked' is retained for
// signature compatibility but is unused in the current design (always
// false), since there is no Lo/Hi drag mechanism.
static bool check_pickup(int idx, float curr, float stored,
                         float tolerance, bool& blocked) {
    if (blocked) {
        if (fabsf(curr - stored) > tolerance * 2.0f) blocked = false;
        return false;
    }
    if (fabsf(curr - stored) <= tolerance) {
        if (++pickup_confirm[idx] >= PICKUP_CONFIRM_CYCLES) return true;
    } else {
        pickup_confirm[idx] = 0;
    }
    return false;
}

// ---------------------------------------------------------------------------
//  Pot -> parameter descriptor table
//
//  Each pot maps to one parameter with a fixed [min,max] range and a pick-up
//  tolerance. Pot 9 (dur_hi) has a dynamic max (= current length), handled as
//  a special case in the mapping functions below.
// ---------------------------------------------------------------------------
enum {
    P_LENGTH = 0, P_BASE_NOTE, P_NOTE_RANGE, P_SLICE_CTR,
    P_STEP_DIV, P_SLICE_WID, P_PLAY_MODE, P_SLICE_BRI, P_DUR_HI
};

struct PotMap {
    int   out_min;
    int   out_max;   // for P_DUR_HI this is overridden at runtime by length
    float tol;
};

static const PotMap POT_MAP[9] = {
    /* idx0 Length      */ { LENGTH_MIN,       LENGTH_MAX,       PICKUP_TOLERANCE },
    /* idx1 Base note   */ { BASE_NOTE_MIN,    BASE_NOTE_MAX,    PICKUP_TOLERANCE },
    /* idx2 Note range  */ { NOTE_RANGE_MIN,   NOTE_RANGE_MAX,   PICKUP_TOLERANCE },
    /* idx3 Slice centre*/ { SLICE_CENTRE_MIN, SLICE_CENTRE_MAX, PICKUP_TOLERANCE_SLICE_CTR },
    /* idx4 Step divider*/ { STEP_DIV_MIN,     STEP_DIV_MAX,     PICKUP_TOLERANCE_STEP_DIV },
    /* idx5 Slice width */ { SLICE_WIDTH_MIN,  SLICE_WIDTH_MAX,  PICKUP_TOLERANCE_SLICE_WID },
    /* idx6 Play mode   */ { PLAY_MODE_MIN,    PLAY_MODE_MAX,    PICKUP_TOLERANCE_PLAY_MODE },
    /* idx7 Slice bright*/ { SLICE_BRIGHT_MIN, SLICE_BRIGHT_MAX, PICKUP_TOLERANCE_SLICE_BRI },
    /* idx8 Dur hi      */ { DUR_MIN_STEPS,    DUR_MAX_STEPS,    PICKUP_TOLERANCE_DUR }, // max overridden
};

// dur_hi upper bound tracks the current length (min 1). Kept as a helper so
// mapping and arming agree.
static int dur_hi_max(const ControllerState& s) {
    int m = (int)s.length;
    if (m < DUR_MIN_STEPS) m = DUR_MIN_STEPS;
    return m;
}

// Map a pot's smoothed ADC to its parameter range (dur_hi uses dynamic max).
static float map_pot(int idx, float smoothed, const ControllerState& s) {
    int lo = POT_MAP[idx].out_min;
    int hi = (idx == P_DUR_HI) ? dur_hi_max(s) : POT_MAP[idx].out_max;
    return (float)map_adc_int(smoothed, lo, hi);
}

// Read the stored parameter value that pot idx drives (for pick-up compare).
static float stored_for(int idx, const ControllerState& s) {
    switch (idx) {
        case P_LENGTH:     return (float)s.length;
        case P_BASE_NOTE:  return (float)s.base_note;
        case P_NOTE_RANGE: return (float)s.note_range;
        case P_SLICE_CTR:  return (float)s.slice_centre;
        case P_STEP_DIV:   return (float)s.step_divider;
        case P_SLICE_WID:  return (float)s.slice_width;
        case P_PLAY_MODE:  return (float)s.play_mode;
        case P_SLICE_BRI:  return (float)s.slice_bright;
        case P_DUR_HI:     return (float)s.dur_hi;
    }
    return 0.0f;
}

// Write a picked-up pot's mapped value into its stored parameter.
static void write_param(int idx, ControllerState& s, float mapped) {
    switch (idx) {
        case P_LENGTH:     s.length       = (uint8_t)mapped;  break;
        case P_BASE_NOTE:  s.base_note    = (uint8_t)mapped;  break;
        case P_NOTE_RANGE: s.note_range   = (uint8_t)mapped;  break;
        case P_SLICE_CTR:  s.slice_centre = (uint16_t)mapped; break;
        case P_STEP_DIV:   s.step_divider = (uint8_t)mapped;  break;
        case P_SLICE_WID:  s.slice_width  = (uint16_t)mapped; break;
        case P_PLAY_MODE:  s.play_mode    = (uint8_t)mapped;  break;
        case P_SLICE_BRI:  s.slice_bright = (uint8_t)mapped;  break;
        case P_DUR_HI:     s.dur_hi       = (uint8_t)mapped;  break;
    }
}

// ---------------------------------------------------------------------------
//  Static state
// ---------------------------------------------------------------------------
static const uint8_t POT_PINS[9] = {
    PIN_POT1, PIN_POT2, PIN_POT3, PIN_POT4, PIN_POT5,
    PIN_POT6, PIN_POT7, PIN_POT8, PIN_POT9
};

static float    prev_mapped[9]    = {0};
static bool     btn_last_state    = false;
static uint32_t btn_last_edge_ms  = 0;

// ---------------------------------------------------------------------------
//  apply_fixed_defaults() — set the non-pot parameters to their fixed values.
//  midi_channel follows controller_id.
// ---------------------------------------------------------------------------
static void apply_fixed_defaults(ControllerState& state) {
    state.vel_lo     = DEFAULT_VEL_LO;
    state.vel_hi     = DEFAULT_VEL_HI;
    state.dur_lo     = DEFAULT_DUR_LO;
    state.param_mode = DEFAULT_PARAM_MODE;
    state.midi_channel = (state.controller_id >= MIDI_CH_MIN &&
                          state.controller_id <= MIDI_CH_MAX)
                             ? state.controller_id : MIDI_CH_MIN;
}

// ---------------------------------------------------------------------------
//  inputs_init()
// ---------------------------------------------------------------------------
void inputs_init() {
    pinMode(PIN_POT1,    INPUT); pinMode(PIN_POT2, INPUT);
    pinMode(PIN_POT3,    INPUT); pinMode(PIN_POT4, INPUT);
    pinMode(PIN_POT5,    INPUT); pinMode(PIN_POT6, INPUT);
    pinMode(PIN_POT7,    INPUT); pinMode(PIN_POT8, INPUT);
    pinMode(PIN_POT9,    INPUT);
    pinMode(PIN_SPDT1,   INPUT_PULLUP);
    pinMode(PIN_SPDT2,   INPUT_PULLUP);
    pinMode(PIN_BTN_DIR, INPUT_PULLUP);

    for (int i = 0; i < 9; i++) {
        g_state.pot_smooth[i]    = -1.0f;
        g_state.pot_picked_up[i] = false;
        g_state.pot_mapped[i]    = 0.0f;
        g_state.pot_blocked[i]   = false;
        prev_mapped[i]           = 0.0f;
        pickup_confirm[i]        = 0;
    }
    btn_last_state   = false;   // released (matches btn_now convention)
    btn_last_edge_ms = 0;
}

// ---------------------------------------------------------------------------
//  inputs_seed_from_pots()
//  FRESH boot. Reads all pots once and populates every pot-driven parameter
//  from its physical position. Fixed-default and button-driven parameters are
//  set to their defaults. All pickup flags are set true (display starts clean).
// ---------------------------------------------------------------------------
void inputs_seed_from_pots(ControllerState& state) {
    for (int i = 0; i < 9; i++) {
        state.pot_smooth[i] = (float)analogRead(POT_PINS[i]);
    }

    // Length must be resolved first so dur_hi's dynamic range is correct.
    state.length = (uint8_t)map_pot(P_LENGTH, state.pot_smooth[P_LENGTH], state);

    for (int i = 0; i < 9; i++) {
        if (i == P_LENGTH) continue;                 // already done
        float m = map_pot(i, state.pot_smooth[i], state);
        write_param(i, state, m);
        state.pot_mapped[i] = m;
    }
    state.pot_mapped[P_LENGTH] = (float)state.length;

    // Fixed defaults + direction default.
    apply_fixed_defaults(state);
    state.play_direction = 1;                        // forward

    for (int i = 0; i < 9; i++) {
        prev_mapped[i]         = state.pot_mapped[i];
        state.pot_picked_up[i] = true;               // start clean — no arrows
        state.pot_blocked[i]   = false;
        pickup_confirm[i]      = 0;
    }

    state.active_page = PAGE_1;                       // always
}

// ---------------------------------------------------------------------------
//  inputs_arm_pickup_from_stored()
//  RESTORED boot. Stored parameter values are already present in `state`
//  (loaded from NVS) and must be preserved. Fixed-default parameters are
//  (re)applied here so a schema change can never leave them stale. Reads pots
//  once, maps each to its range, and arms pick-up per pot: picked-up only if
//  the live pot already matches the stored value within tolerance.
// ---------------------------------------------------------------------------
void inputs_arm_pickup_from_stored(ControllerState& state) {
    for (int i = 0; i < 9; i++) {
        state.pot_smooth[i] = (float)analogRead(POT_PINS[i]);
    }

    // Fixed defaults are not persisted as controls; enforce them regardless of
    // what was loaded (they are informational-only in the blob).
    apply_fixed_defaults(state);

    for (int i = 0; i < 9; i++) {
        float mapped = map_pot(i, state.pot_smooth[i], state);
        float stored = stored_for(i, state);
        state.pot_mapped[i]  = mapped;
        prev_mapped[i]       = mapped;
        state.pot_blocked[i] = false;
        pickup_confirm[i]    = 0;
        state.pot_picked_up[i] = (fabsf(mapped - stored) <= POT_MAP[i].tol);
    }

    state.active_page = PAGE_1;
}

// ---------------------------------------------------------------------------
//  inputs_scan()  — call at SCAN_INTERVAL_MS
// ---------------------------------------------------------------------------
void inputs_scan(ControllerState& state) {

    // -----------------------------------------------------------------
    //  1. IIR-smooth all 9 ADC readings
    // -----------------------------------------------------------------
    float smoothed[9];
    for (int i = 0; i < 9; i++)
        smoothed[i] = iir_update(state.pot_smooth[i], (float)analogRead(POT_PINS[i]));

    // -----------------------------------------------------------------
    //  2. Button: debounced press → toggle play direction on release
    // -----------------------------------------------------------------
    bool btn_now = (digitalRead(PIN_BTN_DIR) == LOW);
    uint32_t now = millis();

    if (!btn_last_state && btn_now) {
        // Falling edge (active LOW) — record edge time
        btn_last_edge_ms = now;
    } else if (btn_last_state && !btn_now) {
        // Rising edge — release
        if (now - btn_last_edge_ms >= BTN_DEBOUNCE_MS) {
            state.play_direction = state.play_direction ? 0 : 1;   // toggle
        }
    }
    btn_last_state = btn_now;

    // -----------------------------------------------------------------
    //  3. Resolve Length first (drives dur_hi's dynamic range this scan)
    // -----------------------------------------------------------------
    {
        float m = map_pot(P_LENGTH, smoothed[P_LENGTH], state);
        state.pot_mapped[P_LENGTH] = m;
        if (!state.pot_picked_up[P_LENGTH]) {
            state.pot_picked_up[P_LENGTH] = check_pickup(
                P_LENGTH, m, (float)state.length,
                POT_MAP[P_LENGTH].tol, state.pot_blocked[P_LENGTH]);
        }
        if (state.pot_picked_up[P_LENGTH])
            state.length = (uint8_t)m;
    }

    // -----------------------------------------------------------------
    //  4. Map + pickup-gate the remaining pots. dur_hi is additionally
    //     clamped to the current length (rescales live as length changes).
    // -----------------------------------------------------------------
    for (int i = 0; i < 9; i++) {
        if (i == P_LENGTH) continue;

        float m = map_pot(i, smoothed[i], state);
        state.pot_mapped[i] = m;

        if (!state.pot_picked_up[i]) {
            state.pot_picked_up[i] = check_pickup(
                i, m, stored_for(i, state), POT_MAP[i].tol, state.pot_blocked[i]);
        }
        if (state.pot_picked_up[i])
            write_param(i, state, m);
    }

    // dur_hi safety clamp: if length shrank below the stored dur_hi, pull it in.
    {
        int dmax = dur_hi_max(state);
        if ((int)state.dur_hi > dmax) state.dur_hi = (uint8_t)dmax;
        if (state.dur_hi < DUR_MIN_STEPS) state.dur_hi = DUR_MIN_STEPS;
    }

    // -----------------------------------------------------------------
    //  5. Advance prev_mapped for next cycle
    // -----------------------------------------------------------------
    for (int i = 0; i < 9; i++) prev_mapped[i] = state.pot_mapped[i];

    // -----------------------------------------------------------------
    //  6. SPDT switches → tx_mode and spdt2_poly
    //
    //  SPDT1 is active HIGH (released = LOW via pullup, engaged = HIGH).
    //  spdt2_poly mirrors the raw physical position of SPDT2 regardless of
    //  SPDT1 (mute) state, so the display can always show MONO/POLY.
    // -----------------------------------------------------------------
    bool muted = (digitalRead(PIN_SPDT1) == HIGH);
    bool poly  = (digitalRead(PIN_SPDT2) == LOW);
    state.spdt2_poly = poly;
    if (muted)     state.tx_mode = MODE_STOPPED;
    else if (poly) state.tx_mode = MODE_POLY;
    else           state.tx_mode = MODE_MONO;
}
