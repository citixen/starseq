// =============================================================================
//  rx_handler.cpp — 8-port concurrent UART RX using SerialPIO
//
//  SerialPIO supports up to 8 unidirectional (RX-only) ports, or 4
//  bidirectional ports.  We use RX-only instances (TX = NOPIN) so that
//  all 8 PIO state machines are available for receiving.
//  The hardware has been left with both TX and RX connections between controller
//  and interface, should that be needed in the future
//
// =============================================================================

#include <SerialPIO.h>
#include "rx_handler.h"
#include "config.h"
#include "controller_state.h"
#include "cobs.h"
#include "crc8.h"

// ---------------------------------------------------------------------------
//  SerialPIO instances — one per controller port, RX-only (TX = NOPIN).
//  Constructor is SerialPIO(tx_pin, rx_pin) — TX comes first.
// ---------------------------------------------------------------------------
static SerialPIO* ctrl_serial[NUM_CONTROLLERS];

// ---------------------------------------------------------------------------
//  Per-port frame accumulation buffer
// ---------------------------------------------------------------------------
struct PortBuffer {
    uint8_t  buf[MAX_FRAME_BYTES];
    uint8_t  pos;

    void reset() { pos = 0; }

    // Returns true if a complete frame was received and stored in buf[0..pos-1]
    bool push(uint8_t byte) {
        if (byte == 0x00) {
            return pos > 0;   // frame complete
        }
        if (pos >= MAX_FRAME_BYTES) {
            reset();           // overflow — discard
            return false;
        }
        buf[pos++] = byte;
        return false;
    }
};

static PortBuffer port_bufs[NUM_CONTROLLERS];

// ---------------------------------------------------------------------------
//  Packet processing
// ---------------------------------------------------------------------------
static uint8_t decode_buf[CTRL_PAYLOAD_LEN + 2];

static void process_frame(uint8_t port_idx) {
    PortBuffer& pb = port_bufs[port_idx];

    uint8_t decoded_len = cobs_decode(pb.buf, pb.pos,
                                      decode_buf, sizeof(decode_buf));
    pb.reset();

    if (decoded_len != CTRL_PAYLOAD_LEN) {
#ifdef DEBUG_RX
        Serial.print(F("[rx] port="));  Serial.print(port_idx + 1);
        Serial.print(F(" DROP len="));  Serial.print(decoded_len);
        Serial.print(F(" expected="));  Serial.println(CTRL_PAYLOAD_LEN);
#endif
        return;
    }

    // CRC check
    uint8_t expected = crc8(decode_buf, CTRL_PAYLOAD_LEN - 1);
    if (expected != decode_buf[CTRL_PAYLOAD_LEN - 1]) {
        state_table[port_idx].crc_errors++;
#ifdef DEBUG_RX
        Serial.print(F("[rx] port="));   Serial.print(port_idx + 1);
        Serial.print(F(" DROP crc got="));
        Serial.print(decode_buf[CTRL_PAYLOAD_LEN - 1]);
        Serial.print(F(" want="));       Serial.println(expected);
#endif
        return;
    }

    // Protocol version check
    if (decode_buf[0] != PROTO_VERSION) {
#ifdef DEBUG_RX
        Serial.print(F("[rx] port="));    Serial.print(port_idx + 1);
        Serial.print(F(" DROP ver="));    Serial.print(decode_buf[0]);
        Serial.print(F(" expected="));    Serial.println(PROTO_VERSION);
#endif
        return;
    }

    // Controller ID check — must match the port it arrived on
    if (decode_buf[1] != port_idx + 1) {
#ifdef DEBUG_RX
        Serial.print(F("[rx] port="));    Serial.print(port_idx + 1);
        Serial.print(F(" DROP id="));     Serial.print(decode_buf[1]);
        Serial.print(F(" expected="));    Serial.println(port_idx + 1);
#endif
        return;
    }

    // Mode check — only 0, 1, 2 are valid
    if (decode_buf[7] > MODE_POLY) {
#ifdef DEBUG_RX
        Serial.print(F("[rx] port="));    Serial.print(port_idx + 1);
        Serial.print(F(" DROP mode="));   Serial.println(decode_buf[7]);
#endif
        return;
    }

    // Update state
    state_table[port_idx].update_from_payload(decode_buf);

#ifdef DEBUG_RX
    const ControllerRecord& r = state_table[port_idx];
    Serial.print(F("[rx] port="));     Serial.print(port_idx + 1);
    Serial.print(F(" seq="));          Serial.print(r.last_seq);
    Serial.print(F(" mode="));         Serial.print(r.mode);
    Serial.print(F(" len="));          Serial.print(r.length);
    Serial.print(F(" ply="));          Serial.print(r.play_mode);
    Serial.print(F(" div="));          Serial.print(r.step_divider);
    Serial.print(F(" prm="));          Serial.print(r.param_mode);
    Serial.print(F(" dir="));          Serial.print(r.play_direction);
    Serial.print(F(" bas="));          Serial.print(r.base_note);
    Serial.print(F(" rng="));          Serial.print(r.note_range);
    Serial.print(F(" vLo="));          Serial.print(r.vel_lo);
    Serial.print(F(" vHi="));          Serial.print(r.vel_hi);
    Serial.print(F(" dLo="));          Serial.print(r.dur_lo);
    Serial.print(F(" dHi="));          Serial.print(r.dur_hi);
    Serial.print(F(" sCtr="));         Serial.print(r.slice_centre);
    Serial.print(F(" sWid="));         Serial.print(r.slice_width);
    Serial.print(F(" sBri="));         Serial.print(r.slice_brightness);
    Serial.print(F(" ch="));           Serial.println(r.midi_channel);
#endif
}

// ---------------------------------------------------------------------------
//  rx_handler_init()
// ---------------------------------------------------------------------------
void rx_handler_init() {
    for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
        port_bufs[i].reset();
        // SerialPIO(tx, rx): NOPIN for TX = RX-only
        ctrl_serial[i] = new SerialPIO(NOPIN, CTRL_RX_PINS[i]);
        ctrl_serial[i]->begin(CTRL_BAUD);
        delay(10);
    }
    Serial.println(F("[rx_handler] 8 SerialPIO RX-only ports initialised"));
}

// ---------------------------------------------------------------------------
//  rx_handler_poll() — call every loop()
// ---------------------------------------------------------------------------
static uint32_t last_status_ms = 0;

void rx_handler_poll() {
    for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
        while (ctrl_serial[i]->available()) {
            uint8_t byte = (uint8_t)ctrl_serial[i]->read();
            if (port_bufs[i].push(byte)) {
                process_frame(i);
            }
        }
    }

    // Periodic stale/offline status update
    uint32_t now = millis();
    if (now - last_status_ms >= 200) {
        last_status_ms = now;
        for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
            state_table[i].update_status();
        }
    }
}
