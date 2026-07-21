#pragma once
#include <Arduino.h>

// CRC-8 Dallas/Maxim, poly 0x31, init 0x00
// Matches serial_tx.cpp on the controller.
uint8_t crc8(const uint8_t* data, uint8_t len);
