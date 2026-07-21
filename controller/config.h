#pragma once
// =============================================================================
//  config.h — Pin assignments, constants, and configurable parameters
//
//  Edit CONTROLLER_ID to set the track number (1–8) for each physical unit 
//  BEFORE flashing
// =============================================================================

// ---------------------------------------------------------------------------
//  Controller identity
// ---------------------------------------------------------------------------
#define CONTROLLER_ID   8       // Set to 1–8 per physical unit

// ---------------------------------------------------------------------------
//  ADC pin assignments
//
//  Single-page mapping (all 9 pots live simultaneously):
//    Pot 1 → Length          Pot 2 → Base note      Pot 3 → Note range
//    Pot 4 → Slice centre    Pot 5 → Step divider   Pot 6 → Slice width
//    Pot 7 → Play mode       Pot 8 → Slice bright   Pot 9 → Duration Hi (1..len)
//
//  All pots are always live. Pick-up is only used at boot when restoring
//  persisted state.
//
// ---------------------------------------------------------------------------
#define PIN_POT1     9      // Length          — GPIO3  (also U0RXD; fine after boot)
#define PIN_POT2     3      // Base note        — GPIO8
#define PIN_POT3     8      // Note range       — GPIO7
#define PIN_POT4     7      // Slice centre     — GPIO6
#define PIN_POT5     6      // Step divider     — GPIO5
#define PIN_POT6     5      // Slice width      — GPIO4
#define PIN_POT7     4      // Play mode        — GPIO1
#define PIN_POT8     2      // Slice brightness — GPIO2
#define PIN_POT9     1      // Duration Hi      — GPIO9

// Digital inputs
#define PIN_SPDT1   15      // Mute/Stop switch     — GPIO15 (active HIGH)
#define PIN_SPDT2   16      // Mono/Poly switch     — GPIO16
#define PIN_BTN_DIR 47      // Direction toggle button — GPIO47

// ---------------------------------------------------------------------------
//  OLED I2C pin assignments  (from CONTROLLER_DESIGN.md)
//  Non-default I2C pins; Wire.begin() is called with these explicitly in
//  display_init()
// ---------------------------------------------------------------------------
#define PIN_I2C_SDA  11     // SDA — GPIO11
#define PIN_I2C_SCL  12     // SCL — GPIO12

// ---------------------------------------------------------------------------
//  OLED display parameters  (SSD1306 128×64, I2C)
// ---------------------------------------------------------------------------
#define OLED_WIDTH      128
#define OLED_HEIGHT      64
#define OLED_RESET_PIN   -1     // No dedicated reset pin; share system reset
#define OLED_I2C_ADDR  0x3C     // Most common SSD1306 address; try 0x3D if not found


// ---------------------------------------------------------------------------
//  Pickup
//  A pot is considered "picked up" when its mapped value comes within
//  PICKUP_TOLERANCE units of the current stored parameter value for
//  PICKUP_CONFIRM_CYCLES consecutive scans.
//
//  Separate tolerances are provided for parameters whose ranges differ widely
//  (e.g. step divider has only 13 steps; slice centre spans 360 degrees).
//
//  Pick-up is used ONLY at boot when restoring persisted state: 
//  any pot whose physical position does not match the restored value is armed 
//  until dialled through. During normal operation all
//  pots are always live and pick-up never re-arms.
// ---------------------------------------------------------------------------
#define PICKUP_TOLERANCE            2   // mapped-value units (general)
#define PICKUP_TOLERANCE_PLAY_MODE  1   // play mode index (0–7, tight range)
#define PICKUP_TOLERANCE_STEP_DIV   1   // step divider index (0–12)
#define PICKUP_TOLERANCE_SLICE_CTR  4   // slice centre degrees (0–359)
#define PICKUP_TOLERANCE_SLICE_WID  4   // slice width degrees (1–360)
#define PICKUP_TOLERANCE_SLICE_BRI  3   // slice brightness (0–100)
#define PICKUP_TOLERANCE_DUR        2   // duration hi (steps, range 1..len)
#define PICKUP_CONFIRM_CYCLES       4   // consecutive scans within tolerance

// ---------------------------------------------------------------------------
//  Serial uplink (Controller → Interface)
//  Uses UART1 (Serial1) with explicit pin assignment.
// ---------------------------------------------------------------------------
#define PIN_SERIAL_RX   17      // GPIO17 — RX from interface (future use)
#define PIN_SERIAL_TX   18      // GPIO18 — TX to interface
#define SERIAL_BAUD     57600

// Heartbeat interval — packet sent regardless of changes
#define HEARTBEAT_MS    500

// Deadband for serial transmission — minimum change before flagging dirty.
#define TX_DEADBAND_BASE_NOTE   1
#define TX_DEADBAND_NOTE_RANGE  1
#define TX_DEADBAND_VEL         1
#define TX_DEADBAND_DUR         1

// Protocol version
// PROTO_VERSION stays 5. Don't worry about what 1 through 4 were
// and make your own version!
#define PROTO_VERSION   5

// ---------------------------------------------------------------------------
//  NVS persistence
//  Independent of PROTO_VERSION: the wire format and the on-flash schema can
//  evolve separately, so they carry separate version tags.
// ---------------------------------------------------------------------------
#define NVS_NAMESPACE       "ctrl_state"  // Preferences namespace
#define NVS_BLOB_KEY        "rec"         // single blob key holding PersistState
#define NVS_STATE_VERSION   1             // on-flash schema version
#define NVS_MAGIC           0x5A          // first-pass sentinel / blank-flash reject

// Write policy timing
#define NVS_SETTLE_MS       750           // defer commit until no change for this long
#define NVS_BACKSTOP_MS     60000         // periodic backstop commit interval

// ---------------------------------------------------------------------------
//  IIR smoothing
//  smoothed = smoothed * (1 - ALPHA) + raw * ALPHA
//  Lower ALPHA = more smoothing, slower response.
//  0.1 gives good noise rejection at 200 Hz scan rate.
// ---------------------------------------------------------------------------
#define POT_IIR_ALPHA   0.10f

// ---------------------------------------------------------------------------
//  Deadband — minimum change in mapped value before updating a stored parameter
// ---------------------------------------------------------------------------
#define DEADBAND_LENGTH     1   // steps
#define DEADBAND_PLAY_MODE  0   // index — any change counts (range is only 0–7)
#define DEADBAND_STEP_DIV   0   // index — any change counts (range is only 0–12)
#define DEADBAND_PARAM_MODE 0   // index — any change counts (range is only 0–2)
#define DEADBAND_BASE_NOTE  1   // MIDI note
#define DEADBAND_NOTE_RANGE 1   // MIDI note
#define DEADBAND_VEL        1   // velocity
#define DEADBAND_DUR        1   // steps
#define DEADBAND_SLICE_CTR  1   // degrees
#define DEADBAND_SLICE_WID  1   // degrees
#define DEADBAND_SLICE_BRI  1   // brightness units
#define DEADBAND_MIDI_CH    0   // channel — any change counts
#define DEADBAND_PLAY_DIR   0   // direction — any change counts (range is 0–1)

// ---------------------------------------------------------------------------
//  Button timing
// ---------------------------------------------------------------------------
#define BTN_DEBOUNCE_MS     20      // ms hold-off after edge
                                    // Short press on release → toggles play
                                    // direction (forward <-> reverse).
                                    // No long-hold gesture - but included
                                    // so one can be added if needed in the
                                    // future

// ---------------------------------------------------------------------------
//  Output ranges
// ---------------------------------------------------------------------------
#define LENGTH_MIN          1
#define LENGTH_MAX         32

#define PLAY_MODE_MIN       0       // random
#define PLAY_MODE_MAX       7       // dimmest

#define STEP_DIV_MIN        0       // index → 1/32
#define STEP_DIV_MAX       12       // index → 4

#define PARAM_MODE_MIN      0       // parameterised
#define PARAM_MODE_MAX      2       // random_per_loop

#define BASE_NOTE_MIN      36       // C2 (MIDI note-name convention: MIDI 0 = C-1)
#define BASE_NOTE_MAX      83       // B5

#define NOTE_RANGE_MIN      0
#define NOTE_RANGE_MAX     24

#define VEL_MIN             0
#define VEL_MAX           127

#define DUR_MIN_STEPS       1       // steps
#define DUR_MAX_STEPS      64

#define SLICE_CENTRE_MIN    0       // degrees, compass bearing, 0 = North
#define SLICE_CENTRE_MAX  359
#define SLICE_WIDTH_MIN     1       // degrees
#define SLICE_WIDTH_MAX   359
#define SLICE_BRIGHT_MIN    0       // 0 = dimmest/most permissive
#define SLICE_BRIGHT_MAX  100

#define MIDI_CH_MIN         1
#define MIDI_CH_MAX        16

#define PLAY_DIR_MIN        0       // reverse (pot fully left)
#define PLAY_DIR_MAX        1       // forward (pot fully right)

// ---------------------------------------------------------------------------
//  Mode constants (transmitted in payload)
// ---------------------------------------------------------------------------
#define MODE_STOPPED    0
#define MODE_MONO       1
#define MODE_POLY       2

// ---------------------------------------------------------------------------
//  Fixed defaults for parameters not driven by a pot but included in payload.
// ---------------------------------------------------------------------------
#define DEFAULT_VEL_LO       80     // fixed velocity low
#define DEFAULT_VEL_HI      120     // fixed velocity high
#define DEFAULT_DUR_LO        1     // fixed duration low (steps)
#define DEFAULT_PARAM_MODE    0     // PARM (parameterised)
// MIDI channel default = controller_id (clamped to 1..16), applied in firmware.

// ---------------------------------------------------------------------------
//  Page constant (retained to enable page-switching future functionality).
//  The current single-page design has no page switching; active_page is 
//  _always_ PAGE_1.
// ---------------------------------------------------------------------------
#define PAGE_1  1
