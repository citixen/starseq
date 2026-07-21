#pragma once
// =============================================================================
//  inputs.h — Input scanning declarations
// =============================================================================

#include "state.h"

// Call once in setup()
void inputs_init();

// Call immediately after inputs_init() on a FRESH boot (no valid persisted
// record).
void inputs_seed_from_pots(ControllerState& state);

// Restored-boot alternative to inputs_seed_from_pots().
void inputs_arm_pickup_from_stored(ControllerState& state);

// Call at SCAN_INTERVAL_MS in loop(). Updates state in place
void inputs_scan(ControllerState& state);
