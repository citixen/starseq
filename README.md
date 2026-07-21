# starseq — project overview

This project and all files in it represent the state of the project as it was during EMF Camp 2026, where it ran as an installation (in the baking sun) for 4 days. It largely worked without incident for that time and the concept and implementation are at least a bit proven. However, the project is offered as-is and without any ability to support it further if you decide to try building one for yourself. It all works in my build, but that doesn't mean it will for you. I may have forgotten critical setup components, and I may have done something weird and forgotten to document it. Sorry if I did. I've also not really documented any of the specifics of how I wired it together in my build. It was horrible spaghetti (see pics) and you can definitely do better just using the pin allocations in the code to guide you. Best of luck! Use this as a jumping off point to something bigger and better! I know I will!

---

## what starseq is

![Image of the control interface for an 8-track sequencer, with a large number of coloured potentiometers and a perspex panel behind which can be seen a raspberry pi](https://github.com/citixen/starseq/blob/main/pics/outsides.png)

**starseq** is an 8-track MIDI step sequencer whose musical content is generated from the real-time positions of naked-eye-visible stars in the sky above the instrument's physical location. Each of the 8 tracks claims a wedge ("slice") of the compass — a band of azimuth and a brightness threshold — and turns whichever stars currently sit inside that wedge into a step sequence: azimuth decides *when* (which step) a note falls, altitude decides *what pitch*, and brightness/colour decide *how loud* and *how long*. Because the sky moves, the sequences drift and evolve on their own, in real astronomical time or sped up/slowed/reversed via a simulated clock. Planets and constellation lines are drawn for visual context only currently — but the data is there for future uses.

The instrument is physically and electronically a three-tier system:

```
┌──────────────────────┐      ┌──────────────────────┐     ┌─────────────────────┐
│ 8 × Instrument       │      │ Controller Interface │     │ Sequencer           │
│ Controllers          │────▶│  (aggregator)        │────▶│ (Raspberry Pi 5)    │
│ (one per track)      │ UART │ RP2040 Pico          │ UART│ Sky engine, MIDI,   │
│ 9 pots + 2 switches  │      │                      │     │ display, output     │
│ + button + OLED      │      │                      │     │                     │
└──────────────────────┘      └──────────────────────┘     └─────────────────────┘
     ESP32-S3 DevKit             8-port aggregator            pygame + skyfield
     per track                  → single uplink               + MIDI + GPIO
```

A performer turns physical pots on 8 identical hand controllers; those settings flow up through an aggregating interface board to a Raspberry Pi, which combines them with live sky data to produce and play an 8-track MIDI sequence, rendered simultaneously as a star-dome visualisation.

The instrument is housed in a standard cheap 104hp eurorack case, with some cheap bulkhead pass-thrus to get USB and HDMI from the Pi outside the case, and to get power in.

---

## tier 1 — instrument controller (one per track, ×8)

**Hardware:** ESP32-S3 DevKit C-1 (cheap - and has 2 x 12-bit SAR ADCs). Per unit: 9 potentiometers, 2 SPDT switches (Mute/Stop; Mono/Poly), 1 momentary push-button (play direction), a 128×64 SSD1306 2 colour (yellow/blue) OLED over I2C (mounted inverted, yellow  strip at the bottom), and a UART link out to the Controller Interface. The PCB files are included for the version used at EMF 26. These were made quickly and down to a price. Better board layouts and control configurations can be achieved!

**Role:** turn physical control positions into a per-track parameter packet and keep the OLED showing current state.

In the published firmware, all 9 pots are live simultaneously on a single page (an earlier multi-page design was collapsed to one page for simplicity). Each pot drives one parameter directly: length, base note, note range, slice centre, step divider, slice width, play mode, slice brightness, and duration max (which rescales live across `1…current length`). The two switches and the button cover mute/stop, mono/poly, and play-direction toggle. Parameters that are sent from the controller but which no longer have a dedicated pot in this  revision — velocity lo/hi, duration lo, parameter mode, MIDI channel — are  held at fixed firmware defaults but are still transmitted in full on every  packet, because **the wire format was deliberately left unchanged** from an  earlier, fuller-featured revision. This means the interface and sequencer  require no changes to accept this simplified controller, and a future firmware  revision could re-expose those parameters on interface pages without touching  downstream code.

The controller debounces inputs, applies deadbanding to pot readings to try  to avoid flooding the serial link with jitter, and transmits change-driven updates plus a periodic heartbeat. It persists its working state to the ESP32's flash-backed NVS (a packed, versioned, CRC-checked 22-byte struct), so a power cycle resumes the previous session instead of resetting to defaults — with **pick-up logic** at boot only: a restored pot value is shown with a directional arrow on the OLED until the performer physically turns that pot through the stored value, at which point it goes live.

---

## tier 2 — controller interface (aggregator)

**Hardware:** a single Raspberry Pi Pico (RP2040), with 8 independent PIO-UART port pairs (one RX/TX pair per controller) plus one hardware UART uplink to the Raspberry Pi. All built onto a small vero board, along with power distribution for the controllers. Takes in a single USB-C connection for 5V.

**Role:** a hardware-agnostic multiplexer. It runs 8 concurrent per-port receivers, validates and decodes each controller's packet (frame boundaries, protocol version, CRC, field ranges), maintains a live state table (one record per controller, with sequence number, last-RX timestamp, and a waiting/online/stale/offline status derived from timeout), and republishes that aggregated state upstream to the Pi as a single serial stream. A single-port fault never blocks the other 7 ports.

Two upstream message shapes exist: periodic **full snapshots** (all 8 controller records in one packet, sent roughly every 400 ms) and **delta packets** (a single controller's record, sent immediately whenever a field changes beyond a small deadband). This keeps the uplink responsive to live pot movement without needing to stream continuously.

---

## tier 3 — sequencer (Raspberry Pi 5)

**Hardware:** a Raspberry Pi 5, with a serial connection to the interface board, a 20 pulse rotary encoder and an SPDT connected to GPIO pins. Outputs HDMI, and has USB connections - all passed through the case.

**Role:** the brain of the instrument. Runs headlessly, receives the  aggregated controller state over serial, computes the live sky, turns  sky + per-track parameters into MIDI, and renders everything to an HDMI/DSI display via pygame.

### architecture

The application is a set of daemon background threads (Serial RX, Input Handler, Sky Engine, Sequence Builder, Sequencer Engine, MIDI Clock Input, GPS Receiver) plus one blocking main-thread loop for the pygame display — pygame's video backend must own the main thread on Linux/the Pi. Shared state moves through thread-safe primitives only: per-track locks, bounded queues, and a lock-free double-buffered (plus one "pending") sequence store per track. The sequencer engine requests real-time (`SCHED_FIFO`) scheduling and is never allowed to block on sky computation, serial I/O, GPS parsing, or rendering.

### midi generation

1. **Sky Engine** recomputes, on a fixed ~250 ms interval, the alt/az of    every star in the Yale Bright Star Catalogue (via Skyfield/DE421) and of     7 planets, using a **simulated clock** that can run at real speed, be     frozen, fast-forwarded, or reversed (a discrete multiplier ladder from     ‑64× to 64×), or jumped to an explicit date via a preset events picker     or manual date fields. Only stars above the horizon and brighter than     magnitude 6.5 (naked-eye) survive into the published snapshot; planets     are published on a separate, sequencing-blind channel.
2. **Sequence Builder** takes each track's slice (`slice_centre` ±    `slice_width/2`, wrap-around handled mod 360) and `slice_brightness`    (mapped to a magnitude cutoff), filters the star snapshot down to that    track's candidate stars, buckets them into steps by azimuth, assigns each    a MIDI note from altitude (mapped onto the valid in-scale notes within    `base_note … base_note + note_range`), and picks which candidate(s) in a    step actually sound according to the track's **play mode** (random,    highest, lowest, middle, first, last, brightest, dimmest) and mono/poly    mode. Velocity comes from magnitude and duration from B‑V colour index    (or from static/per-loop-randomised values, depending on `param_mode`).    Loop-randomised tracks stage their next sequence in a third "pending"    buffer so a re-roll never disturbs a note already playing mid-loop; the    swap happens only at that track's own loop boundary.
3. **Sequencer Engine** is the real-time clock: internal PPQN-24 tick    generation or external MIDI clock, per-track step/tick accumulators so    tracks can run at independent step-dividers while staying phase-locked,    forward/reverse play direction, note-on/note-off scheduling, and MIDI    output. It also drives the flash events consumed by the display so that    firing notes visibly pulse on the star dome and sequencer grid in the    same colour as the track that's playing them.
4. **MIDI channel routing** is decoupled from whatever channel a controller    itself reports: a transport-bar **CH MODE** setting chooses between the    controller-launch default, sequential per-track channels, all-tracks-on-    one-channel, or trusting the controller's own reported channel.

### display

A pygame UI running at 30 fps shows a polar-projected star dome (stars, planet hexagon markers, constellation lines), an 8-row sequencer grid, and an always-visible transport bar (no modal menu — a single focus pointer moves around a flat ring of stops for location, view/brightness toggles, tempo, clock source, key/scale, polyphony limit, MIDI device, channel mode, and simulated time). Layout adapts automatically to portrait, landscape, or extreme-aspect screens, and three independent brightness toggles plus a 10-mode **VIEW** setting control how much of the sky, wedges, and note flashes are visible without ever touching what's actually being sequenced.

### inputs

A rotary encoder + SPDT play/stop switch (GPIO on the Pi) provide local transport control, with a keyboard fallback for headless/dev use. Location can come from config defaults, manual entry, a USB NMEA GPS receiver, or a built-in list of preset cities — switchable live, without a restart.

---

## end-to-end data flow

```
Pot/switch/button position (Instrument Controller)
   → smoothed, deadbanded, mapped to parameter range
   → packed into a 21-byte controller record, COBS-framed, CRC-8
   → UART to Controller Interface

Controller Interface
   → validated per-port, staged into a per-controller state table
   → status (waiting/online/stale/offline) derived from packet recency
   → re-aggregated into full (8-record) or delta (1-record) packets
   → COBS-framed, CRC-8, UART uplink to Raspberry Pi

Raspberry Pi — Serial RX thread
   → CRC-checked, decoded, written directly into that track's TrackState
     under its lock; sequence_dirty = True

Sky Engine (independent of the above)
   → simulated time → star & planet alt/az → filtered snapshot published

Sequence Builder
   → combines the track's parameters with the star snapshot
   → produces a step sequence (notes, velocities, durations)

Sequencer Engine
   → ticks, advances steps, fires MIDI Note On/Off, schedules flash events

MIDI Output + Display
   → notes/clock out over MIDI; star dome & grid rendered in sync
```

A single 21-byte controller record schema is shared verbatim across all three tiers — the Instrument Controller populates it, the Controller Interface forwards it unmodified, and the Sequencer is the only tier that interprets it semantically (resolving the step-divider index to an actual ratio, applying channel-mode overrides, etc.).

---
