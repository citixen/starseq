// =============================================================================
//  Seedquencer — Instrument Controller Firmware
//  controller.ino
//
//  Pot mapping:
//    Pot 1: Length         Pot 2: Base note     Pot 3: Note range
//    Pot 4: Slice centre   Pot 5: Step divider  Pot 6: Slice width
//    Pot 7: Play mode      Pot 8: Slice bright  Pot 9: Duration Hi (1..len)
//
//  Fixed defaults (not pot-driven, transmitted in every payload):
//    Velocity Lo = 80   Velocity Hi = 120   Duration Lo = 1
//    Parameter mode = PARM (0)   MIDI channel = controller_id
//
//  SPDT 1 (PIN_SPDT1): Mute/Stop — tx_mode = 0 when HIGH (engaged).
//  SPDT 2 (PIN_SPDT2): Mono/Poly — tx_mode = 1 (mono) or 2 (poly).
//  Button (PIN_BTN_DIR): toggles play_direction on debounced release.
//
//  Payload: 26 bytes + COBS framing
//
//  Libraries required (install via Arduino Library Manager):
//    - Adafruit SSD1306       (OLED driver)
//    - Adafruit GFX Library   (graphics primitives, dependency of SSD1306)
//    - Adafruit BusIO         (I2C/SPI abstraction, dependency of SSD1306)
//
//  Note:
//    GPIO47 and the free use of GPIO6–11 are only valid on the ESP32-S3.
//    If using a different board you'll need to figure out what works on
//    your version.
//
// =============================================================================

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "config.h"
#include "inputs.h"
#include "display.h"
#include "serial_tx.h"
#include "nvs_store.h"

// ---------------------------------------------------------------------------
//  Timing
// ---------------------------------------------------------------------------
static const uint32_t SCAN_INTERVAL_MS = 5;    // 200 Hz input scan
static const uint32_t OLED_INTERVAL_MS = 50;   // 20 Hz display refresh

static uint32_t lastScanMs = 0;
static uint32_t lastOledMs = 0;

// ---------------------------------------------------------------------------
//  Global state
// ---------------------------------------------------------------------------
ControllerState g_state;

// ---------------------------------------------------------------------------
//  OLED instance
// ---------------------------------------------------------------------------
Adafruit_SSD1306 g_display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET_PIN);

// ---------------------------------------------------------------------------
//  setup()
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    Serial.println(F("BOOT v5"));

    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

    inputs_init();
    serial_tx_init();
    display_init(g_display);
    nvs_store_init();

    g_state.controller_id = CONTROLLER_ID;
    g_state.active_page   = PAGE_1;
    g_state.tx_mode       = MODE_MONO;

    // Attempt to restore persisted parameter state. On success, the loaded values 
    // are preserved and pickup is armed against live pot positions; on failure
    // (no/invalid record) fall back to seeding everything from live pots.
    if (nvs_store_load(g_state)) {
        // Loaded values + restored active_page are already in g_state.
        // Arm pickup without overwriting them.
        inputs_arm_pickup_from_stored(g_state);
        Serial.println(F("Restored state from NVS"));
    } else {
        // Fresh boot: seed all parameters from current pot positions
        // and mark everything picked-up.
        inputs_seed_from_pots(g_state);
        Serial.println(F("No valid NVS record; seeded from pots"));
    }

    // tx_mode is (re)computed from live SPDT positions on the first scan
}

// ---------------------------------------------------------------------------
//  loop()
// ---------------------------------------------------------------------------
void loop() {
    uint32_t now = millis();

    if (now - lastScanMs >= SCAN_INTERVAL_MS) {
        lastScanMs = now;
        inputs_scan(g_state);
        serial_tx_update(g_state);
        nvs_store_update(g_state);   // change-driven, debounced flash persistence
    }

    if (now - lastOledMs >= OLED_INTERVAL_MS) {
        lastOledMs = now;
        display_update(g_display, g_state);
    }
}
