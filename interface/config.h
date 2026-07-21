#pragma once
// =============================================================================
//  config.h — Pin assignments, timing, and protocol constants
// =============================================================================

// ---------------------------------------------------------------------------
//  Controller port pin assignments
//  Each pair is RX/TX on consecutive GPIO numbers.
// ---------------------------------------------------------------------------
#define NUM_CONTROLLERS     8

static const uint8_t CTRL_RX_PINS[NUM_CONTROLLERS] = {  2,  4,  6,  8, 10, 12, 14, 16 };
static const uint8_t CTRL_TX_PINS[NUM_CONTROLLERS] = {  3,  5,  7,  9, 11, 13, 15, 17 };

// ---------------------------------------------------------------------------
//  Uplink to Raspberry Pi (HW UART1)
// ---------------------------------------------------------------------------
#define UPLINK_TX_PIN       20      // GP20
#define UPLINK_RX_PIN       21      // GP21
#define UPLINK_BAUD         57600

// ---------------------------------------------------------------------------
//  Baud rates
// ---------------------------------------------------------------------------
#define CTRL_BAUD           57600   // Controller → Interface

// ---------------------------------------------------------------------------
//  Protocol — must match controller firmware
//
//  downstream payload (Controller → Interface):
//    [0]     Protocol version (5)
//    [1]     Controller ID (1–8)
//    [2]     Sequence number
//    [3–6]   Timestamp ms (uint32 LE)
//    [7]     Mode (0=stopped, 1=mono, 2=poly)
//    [8]     Length (1–32 steps)
//    [9]     Play mode (0–7 index)
//    [10]    Step divider (0–12 index)
//    [11]    Parameter mode (0–2 index)
//    [12]    Play direction (0=reverse, 1=forward)     <-- v5, new
//    [13]    Base note (0–127 MIDI)
//    [14]    Note range (0–127 MIDI)
//    [15]    Velocity Lo (0–127)
//    [16]    Velocity Hi (0–127)
//    [17]    Duration Lo (1–64 steps)
//    [18]    Duration Hi (1–64 steps)
//    [19–20] Slice centre (uint16 LE, 0–359°)
//    [21–22] Slice width  (uint16 LE, 1–360°)
//    [23]    Slice brightness (0–100)
//    [24]    MIDI channel (1–16)
//    [25]    CRC-8 (Dallas/Maxim, poly 0x31) over bytes 0–24
//
// ---------------------------------------------------------------------------
#define PROTO_VERSION       5
#define CTRL_PAYLOAD_LEN    26      // decoded bytes including CRC

// Mode constants
#define MODE_STOPPED        0
#define MODE_MONO           1
#define MODE_POLY           2

// Play direction constants (v5)
#define DIR_REVERSE         0
#define DIR_FORWARD         1

// Upstream packet types
#define PKT_TYPE_FULL       0x01    // Full 8-controller snapshot
#define PKT_TYPE_DELTA      0x02    // Single changed controller record

// ---------------------------------------------------------------------------
//  Timeout policy
// ---------------------------------------------------------------------------
#define STALE_MS            500
#define OFFLINE_MS          2000

// ---------------------------------------------------------------------------
//  Upstream forwarding
// ---------------------------------------------------------------------------
#define SNAPSHOT_INTERVAL_MS    400     // Full snapshot heartbeat

// ---------------------------------------------------------------------------
//  Upstream TX activity LED
//  Onboard LED toggles every TX_LED_PACKET_INTERVAL packets sent (delta or
//  full), as a simple "uplink is alive" indicator independent of the boot
//  blink pattern. Non-blocking — toggled in upstream_tx.cpp, no delay().
// ---------------------------------------------------------------------------
#define TX_LED_PACKET_INTERVAL   2     // Toggle LED every N packets sent

// ---------------------------------------------------------------------------
//  Upstream TX deadbands
//  Minimum change in a field value before flagging a delta for transmission.
// ---------------------------------------------------------------------------
#define TX_DEADBAND_NOTE          1    // base_note, note_range
#define TX_DEADBAND_VEL           1    // vel_lo, vel_hi
#define TX_DEADBAND_DUR           1    // dur_lo, dur_hi (steps)
#define TX_DEADBAND_SLICE_CENTRE  1    // degrees
#define TX_DEADBAND_SLICE_WIDTH   1    // degrees
#define TX_DEADBAND_SLICE_BRIGHT  1    // 0–100 units

// ---------------------------------------------------------------------------
//  RX buffer
// ---------------------------------------------------------------------------
#define MAX_FRAME_BYTES     32      // max COBS-encoded frame size

// ---------------------------------------------------------------------------
//  Onboard LED and VBUS sense
// ---------------------------------------------------------------------------
#define LED_PIN             25      // GP25 — onboard LED
#define VBUS_SENSE_PIN      24      // GP24 — high when powered via USB VBUS

// ---------------------------------------------------------------------------
//  Boot blink pattern
//    USB power  → 2 blinks (short, confirms USB host present)
//    External   → 4 blinks (distinguishes bench/rack power)
// ---------------------------------------------------------------------------
#define BOOT_BLINK_USB      2
#define BOOT_BLINK_EXT      4
#define BOOT_BLINK_MS       150     // on/off period per blink (ms)

// ---------------------------------------------------------------------------
//  Debug output flags
//  Uncomment to enable. DEBUG_ALL enables all flags below it.
// ---------------------------------------------------------------------------
//#define DEBUG_ALL

#ifdef DEBUG_ALL
#  define DEBUG_RX          // Print received packet fields from each controller
#  define DEBUG_TX          // Print upstream delta and snapshot transmissions
#endif

// Fine-grained overrides — uncomment individually if DEBUG_ALL is not set:
//#define DEBUG_RX
//#define DEBUG_TX
