// =============================================================================
//  interface.ino — Seedquencer Interface firmware
//  RP2040 Pico
//
//  Receives serial packets from up to 8 instrument controllers,
//  validates and stores their state, then forwards aggregated state
//  to the Raspberry Pi sequencer over UART1.
//
//      downstream (controller->interface) payload is 26 bytes; upstream
//      (interface->Pi) controller record is 20 bytes. See config.h and
//      controller_state.h / upstream_tx.cpp for the full field layouts.
// =============================================================================

#include "config.h"
#include "controller_state.h"
#include "rx_handler.h"
#include "upstream_tx.h"

// ---------------------------------------------------------------------------
//  Global state table (declared extern in controller_state.h)
// ---------------------------------------------------------------------------
ControllerRecord state_table[NUM_CONTROLLERS];

// ---------------------------------------------------------------------------
//  setup()
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    // Wait up to 1 s for USB serial — skip if no USB host present
    uint32_t serial_wait_start = millis();
    while (!Serial && (millis() - serial_wait_start < 1000)) delay(10);
    Serial.println(F("[interface] Seedquencer Interface booting..."));

    // Initialise state table
    for (uint8_t i = 0; i < NUM_CONTROLLERS; i++) {
        state_table[i].init(i);
    }

    rx_handler_init();
    upstream_tx_init();

    // Detect power source and blink accordingly
    pinMode(VBUS_SENSE_PIN, INPUT);
    pinMode(LED_PIN, OUTPUT);
    uint8_t blink_count = digitalRead(VBUS_SENSE_PIN) ? BOOT_BLINK_USB : BOOT_BLINK_EXT;
    for (uint8_t i = 0; i < blink_count; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(BOOT_BLINK_MS);
        digitalWrite(LED_PIN, LOW);
        delay(BOOT_BLINK_MS);
    }

    Serial.println(F("[interface] Ready."));
}

// ---------------------------------------------------------------------------
//  loop()
// ---------------------------------------------------------------------------
void loop() {
    rx_handler_poll();
    upstream_tx_update();
}
