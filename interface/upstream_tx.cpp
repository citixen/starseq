// =============================================================================
//  upstream_tx.cpp — Upstream serial transmission to Raspberry Pi
//
//  Sends delta packets immediately on state change, and full snapshots
//  periodically as a heartbeat. Packet format must be matched by the
//  receiver.
//
//  Upstream packet format:
//    Header (4 bytes):
//      [0]   Protocol version (PROTO_VERSION = 5)
//      [1]   Packet type (PKT_TYPE_FULL or PKT_TYPE_DELTA)
//      [2–3] Interface timestamp ms (uint16 LE)
//    Body:
//      1 or 8 controller records (RECORD_LEN bytes each — see below)
//    Trailer:
//      CRC-8 (Dallas/Maxim, poly 0x31) over all preceding bytes
//
//  Controller record (21 bytes):
//      [0]     controller_id (1–8)
//      [1]     status (0=waiting, 1=online, 2=stale, 3=offline)
//      [2]     last_seq
//      [3]     mode (0=stopped, 1=mono, 2=poly)
//      [4]     length (1–32 steps)
//      [5]     play_mode (0–7 index)
//      [6]     step_divider (0–12 index; Sequencer resolves to ratio)
//      [7]     param_mode (0–2 index)
//      [8]     play_direction (0=reverse, 1=forward)     <-- v5, new
//      [9]     base_note (0–127 MIDI)
//      [10]    note_range (0–127 MIDI)
//      [11]    vel_lo (0–127)
//      [12]    vel_hi (0–127)
//      [13]    dur_lo (1–64 steps)
//      [14]    dur_hi (1–64 steps)
//      [15–16] slice_centre (uint16 LE, 0–359°)
//      [17–18] slice_width  (uint16 LE, 1–360°)
//      [19]    slice_brightness (0–100)
//      [20]    midi_channel (1–16)
// =============================================================================

#include "upstream_tx.h"
#include "config.h"
#include "controller_state.h"
#include "cobs.h"
#include "crc8.h"

// ---------------------------------------------------------------------------
//  Upstream UART — uses Serial2 (UART1) on GP20/GP21
// ---------------------------------------------------------------------------
#define UPSTREAM_SERIAL     Serial2

// ---------------------------------------------------------------------------
//  Record and packet size constants
// ---------------------------------------------------------------------------
static const uint8_t RECORD_LEN        = 21;
static const uint8_t HEADER_LEN        = 4;
static const uint8_t FULL_PAYLOAD_LEN  = HEADER_LEN + (NUM_CONTROLLERS * RECORD_LEN) + 1;  // +1 CRC
static const uint8_t DELTA_PAYLOAD_LEN = HEADER_LEN + RECORD_LEN + 1;

// ---------------------------------------------------------------------------
//  Encode one controller record into RECORD_LEN bytes
// ---------------------------------------------------------------------------
static void encode_record(const ControllerRecord& rec, uint8_t* out) {
    out[0]  = rec.controller_id;
    out[1]  = rec.status;
    out[2]  = rec.last_seq;
    out[3]  = rec.mode;
    out[4]  = rec.length;
    out[5]  = rec.play_mode;
    out[6]  = rec.step_divider;
    out[7]  = rec.param_mode;
    out[8]  = rec.play_direction;   // v5 — new field
    out[9]  = rec.base_note;
    out[10] = rec.note_range;
    out[11] = rec.vel_lo;
    out[12] = rec.vel_hi;
    out[13] = rec.dur_lo;
    out[14] = rec.dur_hi;
    out[15] = rec.slice_centre & 0xFF;
    out[16] = (rec.slice_centre >> 8) & 0xFF;
    out[17] = rec.slice_width & 0xFF;
    out[18] = (rec.slice_width >> 8) & 0xFF;
    out[19] = rec.slice_brightness;
    out[20] = rec.midi_channel;
}

// ---------------------------------------------------------------------------
//  Send a packet upstream
// ---------------------------------------------------------------------------
static uint8_t payload_buf[FULL_PAYLOAD_LEN];
static uint8_t encoded_buf[FULL_PAYLOAD_LEN + 2];

// TX activity LED — toggles every TX_LED_PACKET_INTERVAL packets sent.
// Non-blocking: just flips pin state on a counter, no delay() on the
// hot send path.
static uint16_t tx_packet_count = 0;
static bool     tx_led_state    = false;

static void send_packet(uint8_t pkt_type, const uint8_t* records,
                        uint8_t num_records) {
    uint32_t ts = millis();
    uint8_t  body_len = HEADER_LEN + (num_records * RECORD_LEN);

    payload_buf[0] = PROTO_VERSION;
    payload_buf[1] = pkt_type;
    payload_buf[2] = ts & 0xFF;
    payload_buf[3] = (ts >> 8) & 0xFF;

    memcpy(payload_buf + HEADER_LEN, records, num_records * RECORD_LEN);
    payload_buf[body_len] = crc8(payload_buf, body_len);

    uint8_t enc_len = cobs_encode(payload_buf, body_len + 1, encoded_buf);
    UPSTREAM_SERIAL.write(encoded_buf, enc_len);
    UPSTREAM_SERIAL.write((uint8_t)0x00);

    tx_packet_count++;
    if (tx_packet_count >= TX_LED_PACKET_INTERVAL) {
        tx_packet_count = 0;
        tx_led_state = !tx_led_state;
        digitalWrite(LED_PIN, tx_led_state ? HIGH : LOW);
    }
}

// ---------------------------------------------------------------------------
//  Dirty detection — last transmitted state per controller
// ---------------------------------------------------------------------------
static ControllerRecord last_sent[NUM_CONTROLLERS];
static bool             first_send = true;

static bool is_dirty(uint8_t i) {
    const ControllerRecord& cur  = state_table[i];
    const ControllerRecord& prev = last_sent[i];

    if (cur.status       != prev.status)       return true;
    if (cur.mode         != prev.mode)         return true;
    if (cur.length       != prev.length)       return true;
    if (cur.play_mode    != prev.play_mode)    return true;
    if (cur.step_divider != prev.step_divider) return true;
    if (cur.param_mode   != prev.param_mode)   return true;
    if (cur.play_direction != prev.play_direction) return true;
    if (abs((int)cur.base_note  - (int)prev.base_note)  > TX_DEADBAND_NOTE)  return true;
    if (abs((int)cur.note_range - (int)prev.note_range) > TX_DEADBAND_NOTE)  return true;
    if (abs((int)cur.vel_lo     - (int)prev.vel_lo)     > TX_DEADBAND_VEL)   return true;
    if (abs((int)cur.vel_hi     - (int)prev.vel_hi)     > TX_DEADBAND_VEL)   return true;
    if (abs((int)cur.dur_lo     - (int)prev.dur_lo)     > TX_DEADBAND_DUR)   return true;
    if (abs((int)cur.dur_hi     - (int)prev.dur_hi)     > TX_DEADBAND_DUR)   return true;
    if (abs((int)cur.slice_centre     - (int)prev.slice_centre)     > TX_DEADBAND_SLICE_CENTRE) return true;
    if (abs((int)cur.slice_width      - (int)prev.slice_width)      > TX_DEADBAND_SLICE_WIDTH)  return true;
    if (abs((int)cur.slice_brightness - (int)prev.slice_brightness) > TX_DEADBAND_SLICE_BRIGHT) return true;
    if (cur.midi_channel != prev.midi_channel) return true;

    return false;
}

// ---------------------------------------------------------------------------
//  upstream_tx_init()
// ---------------------------------------------------------------------------
void upstream_tx_init() {
    UPSTREAM_SERIAL.setTX(UPLINK_TX_PIN);
    UPSTREAM_SERIAL.setRX(UPLINK_RX_PIN);
    UPSTREAM_SERIAL.begin(UPLINK_BAUD);

    for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
        last_sent[i].init(i);
    }
    Serial.println(F("[upstream_tx] UART1 ready on GP20/GP21"));
}

// ---------------------------------------------------------------------------
//  upstream_tx_update() — call every loop()
// ---------------------------------------------------------------------------
static uint32_t last_snapshot_ms = 0;
static uint8_t  record_buf[NUM_CONTROLLERS * RECORD_LEN];

#ifdef DEBUG_TX
static uint32_t delta_count    = 0;
static uint32_t snapshot_count = 0;
#endif

void upstream_tx_update() {
    uint32_t now = millis();

    // Delta packets for changed controllers
    for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
        if (first_send || is_dirty(i)) {
            uint8_t rec[RECORD_LEN];
            encode_record(state_table[i], rec);
            send_packet(PKT_TYPE_DELTA, rec, 1);
            last_sent[i] = state_table[i];
#ifdef DEBUG_TX
            delta_count++;
            Serial.print(F("[upstream_tx] delta ctrl="));
            Serial.print(i + 1);
            Serial.print(F(" mode="));
            Serial.print(state_table[i].mode);
            Serial.print(F(" status="));
            Serial.print(state_table[i].status);
            Serial.print(F(" total_deltas="));
            Serial.println(delta_count);
#endif
        }
    }
    first_send = false;

    // Full snapshot heartbeat
    if (now - last_snapshot_ms >= SNAPSHOT_INTERVAL_MS) {
        for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
            encode_record(state_table[i], record_buf + (i * RECORD_LEN));
        }
        send_packet(PKT_TYPE_FULL, record_buf, NUM_CONTROLLERS);
        last_snapshot_ms = now;
#ifdef DEBUG_TX
        snapshot_count++;
        Serial.print(F("[upstream_tx] snapshot #"));
        Serial.println(snapshot_count);
#endif
    }
}
