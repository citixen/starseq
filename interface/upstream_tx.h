#pragma once
#include <Arduino.h>

// Initialise upstream UART — call once in setup()
void upstream_tx_init();

// Check for dirty state and send packets — call every loop()
void upstream_tx_update();
