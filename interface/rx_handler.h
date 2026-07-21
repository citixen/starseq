#pragma once
#include <Arduino.h>

// Initialise 8 SerialPIO ports — call once in setup()
void rx_handler_init();

// Poll all 8 ports for incoming bytes — call every loop()
void rx_handler_poll();
