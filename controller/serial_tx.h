#pragma once
// =============================================================================
//  serial_tx.h — Serial transmission declarations
// =============================================================================
 
#include "state.h"
 
// Call once in setup() after Wire.begin()
void serial_tx_init();
 
// Call every loop() — sends a packet if any parameter has changed beyond its
// deadband, or if a heartbeat is due.
void serial_tx_update(const ControllerState& state);