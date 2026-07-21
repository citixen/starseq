#pragma once
// =============================================================================
//  display.h — OLED display declarations
// =============================================================================

#include <Adafruit_SSD1306.h>
#include "state.h"

// Call once in setup() — initialises the SSD1306 and shows a boot splash
void display_init(Adafruit_SSD1306& disp);

// Call at OLED_INTERVAL_MS in loop() — redraws the full screen.
// Blue zone shows the single-page parameter grid (8 pot params; Length is in
// the yellow zone) with boot pick-up arrows where applicable.
// Yellow zone shows play state, play direction, Mono/Poly, controller ID, and
// length, continuously.
void display_update(Adafruit_SSD1306& disp, const ControllerState& state);
