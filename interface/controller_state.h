#pragma once
#include <Arduino.h>
#include "config.h"

// ---------------------------------------------------------------------------
//  Controller status
// ---------------------------------------------------------------------------
#define STATUS_WAITING  0
#define STATUS_ONLINE   1
#define STATUS_STALE    2
#define STATUS_OFFLINE  3

// ---------------------------------------------------------------------------
//  ControllerRecord — latest validated state for one controller port
// ---------------------------------------------------------------------------
struct ControllerRecord {
    uint8_t  controller_id;     // 1–8
    uint8_t  status;            // STATUS_* constants above
    uint8_t  last_seq;          // last received sequence number
    uint32_t last_rx_ms;        // millis() at last valid packet

    // Transmitted mode — encodes both play/stop and mono/poly:
    //   0 = stopped/muted  1 = playing mono  2 = playing poly
    uint8_t  mode;

    // Parameters
    uint8_t  length;            // 1–32 steps
    uint8_t  play_mode;         // 0–7 index (random/highest/lowest/middle/first/last/brightest/dimmest)
    uint8_t  step_divider;      // 0–12 index (1/32 … 4)
    uint8_t  base_note;         // 0–127 MIDI
    uint8_t  note_range;        // 0–127 MIDI
    uint8_t  vel_lo;            // 0–127
    uint8_t  vel_hi;            // 0–127
    uint8_t  dur_lo;            // 1–64 steps
    uint8_t  dur_hi;            // 1–64 steps
    uint8_t  param_mode;        // 0–2 index (parameterised/random_static/random_per_loop)
    uint8_t  play_direction;    // 0=reverse, 1=forward (v5)
    uint16_t slice_centre;      // 0–359°
    uint16_t slice_width;       // 1–360°
    uint8_t  slice_brightness;  // 0–100
    uint8_t  midi_channel;      // 1–16

    uint16_t crc_errors;

    void init(uint8_t port_index) {
        //Default values
        controller_id   = port_index + 1;
        status          = STATUS_WAITING;
        last_seq        = 0;
        last_rx_ms      = 0;
        mode            = MODE_STOPPED;
        length          = 16;
        play_mode       = 0;
        step_divider    = 6;    // index 6 = 1/4
        base_note       = 60;   // C4
        note_range      = 12;
        vel_lo          = 60;
        vel_hi          = 100;
        dur_lo          = 4;
        dur_hi          = 16;
        param_mode      = 0;    // parameterised
        play_direction  = DIR_FORWARD;  // default forward
        slice_centre    = 0;
        slice_width     = 30;
        slice_brightness = 50;
        midi_channel    = port_index + 1;
        crc_errors      = 0;
    }

    // Parse a validated CTRL_PAYLOAD_LEN-byte decoded payload and update fields. 
    void update_from_payload(const uint8_t* p) {
        // p[0] = proto version (already checked by caller)
        // p[1] = controller_id (already checked by caller)
        last_seq        = p[2];
        // p[3–6] = timestamp (not stored; last_rx_ms set below)
        mode            = p[7];
        length          = p[8];
        play_mode       = p[9];
        step_divider    = p[10];
        param_mode      = p[11];
        play_direction  = p[12]; 
        base_note       = p[13];
        note_range      = p[14];
        vel_lo          = p[15];
        vel_hi          = p[16];
        dur_lo          = p[17];
        dur_hi          = p[18];
        slice_centre    = p[19] | ((uint16_t)p[20] << 8);
        slice_width     = p[21] | ((uint16_t)p[22] << 8);
        slice_brightness = p[23];
        midi_channel    = p[24];
        // p[25] = CRC (already checked by caller)

        last_rx_ms = millis();
        status     = STATUS_ONLINE;
    }

    // Update stale/offline status — call periodically
    void update_status() {
        if (status == STATUS_WAITING) return;
        uint32_t elapsed = millis() - last_rx_ms;
        if      (elapsed > OFFLINE_MS) status = STATUS_OFFLINE;
        else if (elapsed > STALE_MS)   status = STATUS_STALE;
        else                           status = STATUS_ONLINE;
    }
};

// ---------------------------------------------------------------------------
//  Global state table
// ---------------------------------------------------------------------------
extern ControllerRecord state_table[NUM_CONTROLLERS];
