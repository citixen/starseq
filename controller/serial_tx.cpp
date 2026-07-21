// =============================================================================
//  serial_tx.cpp — Serial packet transmission (Controller → Interface)
//
//  Packet format v5 (all multi-byte fields little-endian):
//
//  Byte  0     : Protocol version (PROTO_VERSION = 5)
//  Byte  1     : Controller ID (1–8)
//  Byte  2     : Sequence number (0–255, wraps)
//  Bytes 3–6   : Timestamp ms (uint32, little-endian)
//  Byte  7     : Mode (0=stopped/muted, 1=mono, 2=poly)
//  Byte  8     : Length (1–32 steps)
//  Byte  9     : Play mode (0–7 index)
//  Byte 10     : Step divider (0–12 index)
//  Byte 11     : Parameter mode (0–2 index)
//  Byte 12     : Play direction (0=reverse, 1=forward)   *** new in v5 ***
//  Byte 13     : Base note (0–127 MIDI)
//  Byte 14     : Note range (0–127 MIDI)
//  Byte 15     : Velocity Lo (0–127)
//  Byte 16     : Velocity Hi (0–127)
//  Byte 17     : Duration Lo (1–64 steps)
//  Byte 18     : Duration Hi (1–64 steps)
//  Bytes 19–20 : Slice centre (uint16, 0–359°, little-endian)
//  Bytes 21–22 : Slice width  (uint16, 1–360°, little-endian)
//  Byte 23     : Slice brightness (0–100)
//  Byte 24     : MIDI channel (1–16)
//  Byte 25     : CRC-8 (Dallas/Maxim, poly 0x31) over bytes 0–24
//
//  Total payload: 26 bytes before COBS encoding.
//
//  COBS framing:
//    The 26-byte payload is COBS-encoded (max 27 bytes encoded) and terminated
//    with a 0x00 delimiter byte. The receiver uses 0x00 as the frame boundary.
//
//  Update policy:
//    - Dirty flags set when any parameter changes beyond its TX_DEADBAND.
//    - Packet sent immediately when dirty.
//    - Heartbeat packet sent every HEARTBEAT_MS regardless of dirty state.
// =============================================================================

#include <Arduino.h>
#include "serial_tx.h"
#include "config.h"
#include "state.h"
#include "crc8.h"

// ---------------------------------------------------------------------------
//  Packet layout constants
// ---------------------------------------------------------------------------
static const uint8_t PAYLOAD_LEN = 26;
static const uint8_t COBS_MAX    = 28;   // COBS(26) + 0x00 delimiter (worst case +2)

// CRC-8 (Dallas/Maxim, poly 0x31, init 0x00) is provided by crc8.h/.cpp,
// shared with the NVS persistence path.

// ---------------------------------------------------------------------------
//  COBS encode
// ---------------------------------------------------------------------------
static uint8_t cobs_encode(const uint8_t* src, uint8_t src_len, uint8_t* dst) {
    uint8_t code_idx = 0;
    uint8_t code     = 1;
    uint8_t out_idx  = 1;

    for (uint8_t i = 0; i < src_len; i++) {
        if (src[i] != 0x00) {
            dst[out_idx++] = src[i];
            code++;
            if (code == 0xFF) {
                dst[code_idx] = code;
                code_idx = out_idx;
                dst[out_idx++] = 0x01;
                code = 1;
            }
        } else {
            dst[code_idx] = code;
            code_idx = out_idx;
            dst[out_idx++] = 0x01;
            code = 1;
        }
    }
    dst[code_idx] = code;
    return out_idx;
}

// ---------------------------------------------------------------------------
//  Last transmitted state — for dirty detection
// ---------------------------------------------------------------------------
static uint8_t  last_tx_mode        = 0xFF;  // sentinel: force first send
static uint8_t  last_tx_length      = 0;
static uint8_t  last_tx_play_mode   = 0;
static uint8_t  last_tx_step_div    = 0;
static uint8_t  last_tx_param_mode  = 0;
static uint8_t  last_tx_play_dir    = 0;
static uint8_t  last_tx_base_note   = 0;
static uint8_t  last_tx_note_range  = 0;
static uint8_t  last_tx_vel_lo      = 0;
static uint8_t  last_tx_vel_hi      = 0;
static uint8_t  last_tx_dur_lo      = 0;
static uint8_t  last_tx_dur_hi      = 0;
static uint16_t last_tx_slice_ctr   = 0;
static uint16_t last_tx_slice_wid   = 0;
static uint8_t  last_tx_slice_bri   = 0;
static uint8_t  last_tx_midi_ch     = 0;

static uint8_t  seq_num   = 0;
static uint32_t last_tx_ms = 0;

// ---------------------------------------------------------------------------
//  is_dirty()
// ---------------------------------------------------------------------------
static bool is_dirty(const ControllerState& s) {
    if (s.tx_mode      != last_tx_mode)      return true;
    if (s.length       != last_tx_length)     return true;
    if (s.play_mode    != last_tx_play_mode)  return true;
    if (s.step_divider != last_tx_step_div)   return true;
    if (s.param_mode   != last_tx_param_mode) return true;
    if (s.play_direction != last_tx_play_dir) return true;
    if (abs((int)s.base_note  - (int)last_tx_base_note)  > TX_DEADBAND_BASE_NOTE)  return true;
    if (abs((int)s.note_range - (int)last_tx_note_range) > TX_DEADBAND_NOTE_RANGE) return true;
    if (abs((int)s.vel_lo     - (int)last_tx_vel_lo)     > TX_DEADBAND_VEL)        return true;
    if (abs((int)s.vel_hi     - (int)last_tx_vel_hi)     > TX_DEADBAND_VEL)        return true;
    if (abs((int)s.dur_lo     - (int)last_tx_dur_lo)     > TX_DEADBAND_DUR)        return true;
    if (abs((int)s.dur_hi     - (int)last_tx_dur_hi)     > TX_DEADBAND_DUR)        return true;
    if (s.slice_centre != last_tx_slice_ctr)  return true;
    if (s.slice_width  != last_tx_slice_wid)  return true;
    if (s.slice_bright != last_tx_slice_bri)  return true;
    if (s.midi_channel != last_tx_midi_ch)    return true;
    return false;
}

// ---------------------------------------------------------------------------
//  update_last_tx()
// ---------------------------------------------------------------------------
static void update_last_tx(const ControllerState& s) {
    last_tx_mode       = s.tx_mode;
    last_tx_length     = s.length;
    last_tx_play_mode  = s.play_mode;
    last_tx_step_div   = s.step_divider;
    last_tx_param_mode = s.param_mode;
    last_tx_play_dir   = s.play_direction;
    last_tx_base_note  = s.base_note;
    last_tx_note_range = s.note_range;
    last_tx_vel_lo     = s.vel_lo;
    last_tx_vel_hi     = s.vel_hi;
    last_tx_dur_lo     = s.dur_lo;
    last_tx_dur_hi     = s.dur_hi;
    last_tx_slice_ctr  = s.slice_centre;
    last_tx_slice_wid  = s.slice_width;
    last_tx_slice_bri  = s.slice_bright;
    last_tx_midi_ch    = s.midi_channel;
}

// ---------------------------------------------------------------------------
//  build_and_send()
// ---------------------------------------------------------------------------
static void build_and_send(const ControllerState& s) {
    uint8_t payload[PAYLOAD_LEN];
    uint8_t encoded[COBS_MAX];

    uint32_t ts = millis();

    payload[0]  = PROTO_VERSION;
    payload[1]  = s.controller_id;
    payload[2]  = seq_num++;
    payload[3]  = (uint8_t)(ts & 0xFF);
    payload[4]  = (uint8_t)((ts >>  8) & 0xFF);
    payload[5]  = (uint8_t)((ts >> 16) & 0xFF);
    payload[6]  = (uint8_t)((ts >> 24) & 0xFF);
    payload[7]  = s.tx_mode;
    payload[8]  = s.length;
    payload[9]  = s.play_mode;
    payload[10] = s.step_divider;
    payload[11] = s.param_mode;
    payload[12] = s.play_direction;
    payload[13] = s.base_note;
    payload[14] = s.note_range;
    payload[15] = s.vel_lo;
    payload[16] = s.vel_hi;
    payload[17] = s.dur_lo;
    payload[18] = s.dur_hi;
    payload[19] = (uint8_t)(s.slice_centre & 0xFF);
    payload[20] = (uint8_t)((s.slice_centre >> 8) & 0xFF);
    payload[21] = (uint8_t)(s.slice_width & 0xFF);
    payload[22] = (uint8_t)((s.slice_width >> 8) & 0xFF);
    payload[23] = s.slice_bright;
    payload[24] = s.midi_channel;
    payload[25] = crc8(payload, 25);   // CRC over bytes 0–24

    uint8_t enc_len = cobs_encode(payload, PAYLOAD_LEN, encoded);

    Serial1.write(encoded, enc_len);
    Serial1.write((uint8_t)0x00);   // frame delimiter

    // Debug echo to USB serial monitor
    Serial.print(F("TX seq="));   Serial.print(payload[2]);
    Serial.print(F(" mode="));    Serial.print(payload[7]);
    Serial.print(F(" len="));     Serial.print(payload[8]);
    Serial.print(F(" ply="));     Serial.print(payload[9]);
    Serial.print(F(" div="));     Serial.print(payload[10]);
    Serial.print(F(" prm="));     Serial.print(payload[11]);
    Serial.print(F(" dir="));     Serial.print(payload[12]);
    Serial.print(F(" bas="));     Serial.print(payload[13]);
    Serial.print(F(" rng="));     Serial.print(payload[14]);
    Serial.print(F(" vLo="));     Serial.print(payload[15]);
    Serial.print(F(" vHi="));     Serial.print(payload[16]);
    Serial.print(F(" dLo="));     Serial.print(payload[17]);
    Serial.print(F(" dHi="));     Serial.print(payload[18]);
    uint16_t sc = payload[19] | ((uint16_t)payload[20] << 8);
    uint16_t sw = payload[21] | ((uint16_t)payload[22] << 8);
    Serial.print(F(" sCtr="));    Serial.print(sc);
    Serial.print(F(" sWid="));    Serial.print(sw);
    Serial.print(F(" sBri="));    Serial.print(payload[23]);
    Serial.print(F(" ch="));      Serial.print(payload[24]);
    Serial.print(F(" crc="));     Serial.println(payload[25]);

    update_last_tx(s);
    last_tx_ms = millis();
}

// ---------------------------------------------------------------------------
//  serial_tx_init()
// ---------------------------------------------------------------------------
void serial_tx_init() {
    Serial1.begin(SERIAL_BAUD, SERIAL_8N1, PIN_SERIAL_RX, PIN_SERIAL_TX);
    last_tx_mode = 0xFF;   // force first packet
    last_tx_ms   = 0;
    seq_num      = 0;
}

// ---------------------------------------------------------------------------
//  serial_tx_update()
// ---------------------------------------------------------------------------
void serial_tx_update(const ControllerState& state) {
    uint32_t now = millis();
    if (is_dirty(state) || (now - last_tx_ms >= HEARTBEAT_MS)) {
        build_and_send(state);
    }
}
