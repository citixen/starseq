#pragma once
// =============================================================================
//  state.h — ControllerState struct
//
//  Single shared data container passed between the input scanner, serial
//  transmitter, and display. All modules operate on the same instance
//  (g_state, defined in controller.ino).
//
//      Pot 1 → length        Pot 2 → base_note     Pot 3 → note_range
//      Pot 4 → slice_centre  Pot 5 → step_divider  Pot 6 → slice_width
//      Pot 7 → play_mode     Pot 8 → slice_bright  Pot 9 → dur_hi (1..length)
//
//    The momentary button toggles play_direction (forward <-> reverse).
//
//    active_page is retained solely for the persisted record and is always
//    PAGE_1. pot_mapped[i] reflects each pot's physical position mapped to its
//    parameter range; pot_picked_up[i] gates whether that live reading drives
//    the stored parameter (relevant only during boot pick-up).
// =============================================================================

struct ControllerState {

    // -------------------------------------------------------------------------
    //  Identity
    // -------------------------------------------------------------------------
    uint8_t  controller_id;         // 1–8

    // -------------------------------------------------------------------------
    //  Page (retained for future development of multi-page contoller interface
    //  only; always PAGE_1)
    // -------------------------------------------------------------------------
    uint8_t  active_page;

    // -------------------------------------------------------------------------
    //  Transmitted mode
    //  Derived each scan from the SPDT switches:
    //    SPDT1 engaged (HIGH) → MODE_STOPPED (0)
    //    SPDT1 released (LOW) + SPDT2 released → MODE_MONO (1)
    //    SPDT1 released (LOW) + SPDT2 engaged  → MODE_POLY (2)
    // -------------------------------------------------------------------------
    uint8_t  tx_mode;               // 0=stopped, 1=mono, 2=poly

    // -------------------------------------------------------------------------
    //  Raw SPDT2 (Mono/Poly) position, independent of mute state.
    //  Updated every scan regardless of SPDT1. Allows the display to show
    //  the physical Mono/Poly switch position even when the track is stopped.
    //    false = Mono (SPDT2 released)
    //    true  = Poly (SPDT2 engaged)
    // -------------------------------------------------------------------------
    bool     spdt2_poly;            // true = Poly, false = Mono

    // -------------------------------------------------------------------------
    //  Parameters — pot-driven (all live, single page)
    //    Pot 1 → length        Pot 2 → base_note     Pot 3 → note_range
    //    Pot 4 → slice_centre  Pot 5 → step_divider  Pot 6 → slice_width
    //    Pot 7 → play_mode     Pot 8 → slice_bright  Pot 9 → dur_hi (1..length)
    // -------------------------------------------------------------------------
    uint8_t  length;                // 1–32 steps      (Pot 1)
    uint8_t  play_mode;             // 0–7 index       (Pot 7)
    uint8_t  step_divider;          // 0–12 index      (Pot 5)
    uint8_t  base_note;             // 0–127 MIDI      (Pot 2)
    uint8_t  note_range;            // 0–127 MIDI      (Pot 3)
    uint16_t slice_centre;          // 0–359°          (Pot 4)
    uint16_t slice_width;           // 1–360°          (Pot 6)
    uint8_t  slice_bright;          // 0–100           (Pot 8)
    uint8_t  dur_hi;                // 1..length steps (Pot 9)

    // -------------------------------------------------------------------------
    //  Parameters — fixed firmware defaults (not pot-driven, still transmitted)
    //    vel_lo   = DEFAULT_VEL_LO      vel_hi     = DEFAULT_VEL_HI
    //    dur_lo   = DEFAULT_DUR_LO      param_mode = DEFAULT_PARAM_MODE
    //    midi_channel = controller_id (clamped to 1..16)
    // -------------------------------------------------------------------------
    uint8_t  vel_lo;                // 0–127  (fixed)
    uint8_t  vel_hi;                // 0–127  (fixed)
    uint8_t  dur_lo;                // 1–64 steps (fixed)
    uint8_t  param_mode;            // 0–2 index (fixed)
    uint8_t  midi_channel;          // 1–16 (= controller_id)

    // -------------------------------------------------------------------------
    //  Play direction — toggled by the momentary button (not a pot)
    // -------------------------------------------------------------------------
    uint8_t  play_direction;        // 0 = reverse, 1 = forward

    // -------------------------------------------------------------------------
    //  Internal IIR filter states (one per pot, raw ADC smoothed)
    // -------------------------------------------------------------------------
    float    pot_smooth[9];         // updated by inputs_scan()

    // -------------------------------------------------------------------------
    //  Current mapped pot positions (in parameter units).
    //  Always reflects physical pot position regardless of pickup state.
    //  Used by the display to draw boot pick-up direction arrows.
    // -------------------------------------------------------------------------
    float    pot_mapped[9];

    // -------------------------------------------------------------------------
    //  Pickup flags (one per pot)
    //  During normal operation all are true (pots always live). Set false at
    //  boot for any pot whose position does not match the NVS-restored value,
    //  until the pot is dialled through it.
    // -------------------------------------------------------------------------
    bool     pot_picked_up[9];

    // -------------------------------------------------------------------------
    //  Blocked flags (one per pot)
    //  Retained by the pick-up helper's signature; unused in the single-page
    //  design (no Lo/Hi drag). Always false.
    // -------------------------------------------------------------------------
    bool     pot_blocked[9];
};

// Global instance declared in controller.ino
extern ControllerState g_state;
