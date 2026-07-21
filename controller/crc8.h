#pragma once
// =============================================================================
//  crc8.h — Shared CRC-8 (Dallas/Maxim, polynomial 0x31, init 0x00)
//
//  Single implementation used by both the serial wire path (serial_tx.cpp)
//  and the NVS persistence path (nvs_store.cpp) so the two never diverge.
// =============================================================================

#include <stdint.h>

// CRC-8, Dallas/Maxim: polynomial 0x31 (x^8 + x^5 + x^4 + 1), init 0x00.
uint8_t crc8(const uint8_t* data, uint8_t len);
