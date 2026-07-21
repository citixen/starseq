#pragma once
#include <Arduino.h>

// COBS decode — src is the frame without the 0x00 delimiter.
// dst must be at least src_len bytes.
// Returns decoded length, or 0 if malformed.
uint8_t cobs_decode(const uint8_t* src, uint8_t src_len,
                    uint8_t* dst, uint8_t dst_max);

// COBS encode — src is the raw payload.
// dst must be at least src_len + 2 bytes.
// Returns encoded length (not including terminating 0x00).
uint8_t cobs_encode(const uint8_t* src, uint8_t src_len, uint8_t* dst);
