#pragma once
// =============================================================================
//  nvs_store.h — Non-volatile parameter persistence (ESP32-S3 NVS)
//
//  Stores one packed, versioned, CRC-protected record per controller in a
//  single NVS blob key, so parameter state survives a power cycle. 
// =============================================================================

#include "state.h"

// Call once in setup(), before loading state. Opens the NVS namespace.
// Returns true if NVS is available; false disables persistence for the session
// (the controller still runs normally, just without save/restore).
bool nvs_store_init();

// Attempt to load and validate a persisted record into `state`.
// On success, the parameter fields and active_page of `state` are populated
// from flash and the function returns true. On any failure (no record, bad
// magic/version/CRC, or an out-of-range field) `state` is left untouched and
// the function returns false, and the caller should seed from live pots as
// usual. Does NOT touch tx_mode / spdt2_poly (those are always recomputed
// live from the switches).
bool nvs_store_load(ControllerState& state);

// Call every loop(). Detects meaningful parameter changes, debounces them
// (NVS_SETTLE_MS after the last change), and commits a single blob write once
// motion settles. Also performs a periodic backstop commit every
// NVS_BACKSTOP_MS. Never blocks on the settle window; the actual flash commit
// is a short synchronous call made at most once per settle/backstop event.
void nvs_store_update(const ControllerState& state);
