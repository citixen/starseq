// =============================================================================
//  nvs_store.cpp — Non-volatile parameter persistence (ESP32-S3 NVS)
//
//  Persists one packed, versioned, CRC-protected record per controller in a
//  single NVS blob key via the Arduino-ESP32 Preferences library.
//
//  Record format (PersistState, packed, 22 bytes):
//    [0]    magic          (NVS_MAGIC)
//    [1]    state_version  (NVS_STATE_VERSION)
//    [2]    mode           (informational only; live SPDT read wins at boot)
//    [3]    length         1–32
//    [4]    play_mode      0–7
//    [5]    step_divider   0–12
//    [6]    param_mode     0–2
//    [7]    base_note      36–83 (C2..B5)
//    [8]    note_range     0–127
//    [9]    vel_lo         0–127
//    [10]   vel_hi         0–127
//    [11]   dur_lo         1–64
//    [12]   dur_hi         1–64
//    [13-14] slice_centre  uint16 LE, 0–359
//    [15-16] slice_width   uint16 LE, 1–360
//    [17]   slice_bright   0–100
//    [18]   midi_channel   1–16
//    [19]   play_direction 0–1
//    [20]   active_page    1–2
//    [21]   crc            CRC-8 over bytes 0–20
//
//  Write path is decoupled from serial TX: this module keeps its own snapshot
//  of the last-committed parameters and its own settle/backstop timers.
// =============================================================================

#include <Arduino.h>
#include <Preferences.h>
#include "nvs_store.h"
#include "config.h"
#include "state.h"
#include "crc8.h"

// ---------------------------------------------------------------------------
//  Packed on-flash record
// ---------------------------------------------------------------------------
struct __attribute__((packed)) PersistState {
    uint8_t  magic;
    uint8_t  state_version;
    uint8_t  mode;            // informational only
    uint8_t  length;
    uint8_t  play_mode;
    uint8_t  step_divider;
    uint8_t  param_mode;
    uint8_t  base_note;
    uint8_t  note_range;
    uint8_t  vel_lo;
    uint8_t  vel_hi;
    uint8_t  dur_lo;
    uint8_t  dur_hi;
    uint16_t slice_centre;    // LE on ESP32 (little-endian core)
    uint16_t slice_width;
    uint8_t  slice_bright;
    uint8_t  midi_channel;
    uint8_t  play_direction;
    uint8_t  active_page;
    uint8_t  crc;             // over all preceding bytes (0 .. sizeof-2)
};

static const uint8_t REC_LEN = sizeof(PersistState);          // 22
static const uint8_t CRC_SPAN = (uint8_t)(sizeof(PersistState) - 1); // 21

// ---------------------------------------------------------------------------
//  Module state
// ---------------------------------------------------------------------------
static Preferences  prefs;
static bool         nvs_ok            = false;   // namespace opened OK

static PersistState last_committed;              // snapshot of last flash write
static bool         have_committed    = false;   // is last_committed valid?
static PersistState last_seen;                   // most recent value observed
static bool         have_seen         = false;   // is last_seen valid?
static bool         change_pending    = false;   // a change awaiting settle
static uint32_t     last_change_ms    = 0;       // when motion was last observed
static uint32_t     last_commit_ms    = 0;       // for the periodic backstop

// ---------------------------------------------------------------------------
//  pack() — build a PersistState (incl. magic/version/CRC) from live state
// ---------------------------------------------------------------------------
static void pack(const ControllerState& s, PersistState& r) {
    r.magic          = NVS_MAGIC;
    r.state_version  = NVS_STATE_VERSION;
    r.mode           = s.tx_mode;
    r.length         = s.length;
    r.play_mode      = s.play_mode;
    r.step_divider   = s.step_divider;
    r.param_mode     = s.param_mode;
    r.base_note      = s.base_note;
    r.note_range     = s.note_range;
    r.vel_lo         = s.vel_lo;
    r.vel_hi         = s.vel_hi;
    r.dur_lo         = s.dur_lo;
    r.dur_hi         = s.dur_hi;
    r.slice_centre   = s.slice_centre;
    r.slice_width    = s.slice_width;
    r.slice_bright   = s.slice_bright;
    r.midi_channel   = s.midi_channel;
    r.play_direction = s.play_direction;
    r.active_page    = s.active_page;
    r.crc            = crc8((const uint8_t*)&r, CRC_SPAN);
}

// ---------------------------------------------------------------------------
//  validate() — magic, version, CRC, and per-field range checks
// ---------------------------------------------------------------------------
static bool validate(const PersistState& r) {
    if (r.magic         != NVS_MAGIC)         return false;
    if (r.state_version != NVS_STATE_VERSION) return false;
    if (crc8((const uint8_t*)&r, CRC_SPAN) != r.crc) return false;

    // Per-field range checks. mode is not range-checked here: it is
    // informational and is never applied to live state at boot.
    if (r.length       < LENGTH_MIN     || r.length       > LENGTH_MAX)     return false;
    if (r.play_mode    > PLAY_MODE_MAX)                                     return false;
    if (r.step_divider > STEP_DIV_MAX)                                      return false;
    if (r.param_mode   > PARAM_MODE_MAX)                                    return false;
    if (r.base_note    < BASE_NOTE_MIN  || r.base_note    > BASE_NOTE_MAX)  return false;
    if (r.note_range   > NOTE_RANGE_MAX)                                    return false;
    if (r.vel_lo       > VEL_MAX)                                           return false;
    if (r.vel_hi       > VEL_MAX)                                           return false;
    if (r.vel_lo       > r.vel_hi)                                          return false;
    if (r.dur_lo       < DUR_MIN_STEPS  || r.dur_lo       > DUR_MAX_STEPS)  return false;
    if (r.dur_hi       < DUR_MIN_STEPS  || r.dur_hi       > DUR_MAX_STEPS)  return false;
    if (r.dur_lo       > r.dur_hi)                                          return false;
    if (r.slice_centre > SLICE_CENTRE_MAX)                                  return false;
    if (r.slice_width  < SLICE_WIDTH_MIN || r.slice_width > 360)            return false;
    if (r.slice_bright > SLICE_BRIGHT_MAX)                                  return false;
    if (r.midi_channel < MIDI_CH_MIN    || r.midi_channel > MIDI_CH_MAX)    return false;
    if (r.play_direction > PLAY_DIR_MAX)                                    return false;
    // active_page is not range-checked strictly: the single-page design always
    // runs on PAGE_1, and legacy (two-page) records are coerced in apply().
    return true;
}

// ---------------------------------------------------------------------------
//  apply() — copy a validated record's parameters into live state.
//  Does not touch tx_mode / spdt2_poly (recomputed live from switches).
// ---------------------------------------------------------------------------
static void apply(const PersistState& r, ControllerState& s) {
    s.length         = r.length;
    s.play_mode      = r.play_mode;
    s.step_divider   = r.step_divider;
    s.param_mode     = r.param_mode;
    s.base_note      = r.base_note;
    s.note_range     = r.note_range;
    s.vel_lo         = r.vel_lo;
    s.vel_hi         = r.vel_hi;
    s.dur_lo         = r.dur_lo;
    s.dur_hi         = r.dur_hi;
    s.slice_centre   = r.slice_centre;
    s.slice_width    = r.slice_width;
    s.slice_bright   = r.slice_bright;
    s.midi_channel   = r.midi_channel;
    s.play_direction = r.play_direction;
    s.active_page    = PAGE_1;   // single-page design: always PAGE_1
}

// ---------------------------------------------------------------------------
//  params_differ() — compare the parameter payload of two records, ignoring
//  volatile / informational fields (crc, mode). active_page IS compared so a
//  page change alone triggers a save (cheap, and keeps restore accurate).
// ---------------------------------------------------------------------------
static bool params_differ(const PersistState& a, const PersistState& b) {
    return a.length         != b.length        ||
           a.play_mode      != b.play_mode     ||
           a.step_divider   != b.step_divider  ||
           a.param_mode     != b.param_mode    ||
           a.base_note      != b.base_note      ||
           a.note_range     != b.note_range     ||
           a.vel_lo         != b.vel_lo         ||
           a.vel_hi         != b.vel_hi         ||
           a.dur_lo         != b.dur_lo         ||
           a.dur_hi         != b.dur_hi         ||
           a.slice_centre   != b.slice_centre   ||
           a.slice_width    != b.slice_width    ||
           a.slice_bright   != b.slice_bright   ||
           a.midi_channel   != b.midi_channel   ||
           a.play_direction != b.play_direction ||
           a.active_page    != b.active_page;
}

// ---------------------------------------------------------------------------
//  commit() — write the given record to flash. Short synchronous NVS put.
// ---------------------------------------------------------------------------
static bool commit(const PersistState& r) {
    if (!nvs_ok) return false;
    size_t n = prefs.putBytes(NVS_BLOB_KEY, &r, REC_LEN);
    if (n != REC_LEN) {
        // Write failed (e.g. flash wear-out). Persistence is best-effort:
        // do not disturb live operation; just report and carry on.
        Serial.println(F("nvs_store: commit failed"));
        return false;
    }
    last_committed = r;
    have_committed = true;
    last_commit_ms = millis();
    return true;
}

// ---------------------------------------------------------------------------
//  nvs_store_init()
// ---------------------------------------------------------------------------
bool nvs_store_init() {
    // read/write mode
    nvs_ok = prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
    if (!nvs_ok) {
        Serial.println(F("nvs_store: namespace open failed; persistence disabled"));
    }
    have_committed = false;
    change_pending = false;
    last_change_ms = 0;
    last_commit_ms = millis();
    return nvs_ok;
}

// ---------------------------------------------------------------------------
//  nvs_store_load()
// ---------------------------------------------------------------------------
bool nvs_store_load(ControllerState& state) {
    if (!nvs_ok) return false;

    PersistState r;
    size_t got = prefs.getBytes(NVS_BLOB_KEY, &r, REC_LEN);
    if (got != REC_LEN) {
        // No record, or wrong size (e.g. an older/newer schema length).
        return false;
    }
    if (!validate(r)) {
        Serial.println(F("nvs_store: stored record invalid; using defaults"));
        return false;
    }

    apply(r, state);

    // Seed the commit snapshot so we don't immediately re-write the record
    // we just loaded. mode/crc in the snapshot are refreshed on next pack().
    last_committed = r;
    have_committed = true;
    Serial.println(F("nvs_store: restored persisted state"));
    return true;
}

// ---------------------------------------------------------------------------
//  nvs_store_update()
//
//  Change-driven. Debounced. A parameter change (re)arms the settle timer;
//  the commit fires once nothing has changed for NVS_SETTLE_MS. A periodic
//  backstop commit fires every NVS_BACKSTOP_MS if the current state differs
//  from what is on flash, covering a change followed by power loss inside the
//  settle window.
// ---------------------------------------------------------------------------
void nvs_store_update(const ControllerState& state) {
    if (!nvs_ok) return;

    uint32_t now = millis();

    PersistState cur;
    pack(state, cur);

    bool differs_from_flash = !have_committed || params_differ(cur, last_committed);

    if (differs_from_flash) {
        // Whenever the value moves relative to what we last observed, (re)arm
        // the settle window. A pot being swept keeps re-arming, coalescing the
        // whole sweep into a single commit once it stops.
        if (!have_seen || params_differ(cur, last_seen)) {
            last_seen      = cur;
            have_seen      = true;
            last_change_ms = now;
            change_pending = true;
        }

        // Commit once the value has been stable for the full settle window.
        if (change_pending && (now - last_change_ms >= NVS_SETTLE_MS)) {
            if (commit(cur)) change_pending = false;
        }
    } else {
        // Back in sync with flash — nothing pending.
        change_pending = false;
        have_seen      = false;
    }

    // Periodic backstop: if flash is stale and we're not mid-settle, commit.
    // Guards against a change followed by power loss inside the settle window.
    if (!change_pending &&
        (now - last_commit_ms >= NVS_BACKSTOP_MS) &&
        (!have_committed || params_differ(cur, last_committed))) {
        commit(cur);
    }
}
