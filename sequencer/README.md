# starseq

An 8-track MIDI step sequencer whose musical sequences are derived from the real-time positions of naked-eye-visible stars in the sky above the instrument's location. Runs headlessly on a Raspberry Pi 5 with a pygame UI on an attached HDMI or DSI display.

---

## Hardware requirements

| Component | Notes |
|---|---|
| Raspberry Pi 5 | Tested target; Pi 4 may work with reduced sky recalculation rate |
| HDMI or DSI display | Any resolution ≥ 800 × 480 |
| MIDI interface | USB class-compliant or GPIO UART MIDI out |
| Controller interface | Connected to UART0 (BCM 14/15) at 57600 8N1 |
| Rotary encoder | CLK → BCM 17, DT → BCM 18, SW → BCM 27 (pull-ups applied in software) |
| SPDT play/stop switch | → BCM 16 (pull-up applied in software) |

All hardware inputs are optional at runtime — see [Command-line arguments](#command-line-arguments).

---

## OS requirements

**Raspberry Pi OS Bookworm Lite** (headless, no desktop environment). A desktop environment is not required or expected. The display is driven directly via KMS/DRM.

---

## Software installation

### 1. Clone the repo to the Pi

```bash
git clone <repo-url> ~/starseq
cd ~/starseq
```

Or copy files over SSH:

```bash
scp -r ./starseq pi@<pi-address>:~/starseq
```

### 2. Install system SDL2 development packages

pygame must be compiled against the system SDL2 to gain KMS/DRM display support. Install the development headers first:

```bash
sudo apt update
sudo apt install --no-install-recommends \
    libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev \
    libsdl2-mixer-dev python3-dev
```

### 3. Create and activate a Python virtual environment

```bash
cd ~/starseq
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 5. Install pygame from source

The pre-built pygame wheel from PyPI bundles its own SDL2 which does not include the KMS/DRM driver required for Bookworm Lite. Compiling from source links against the system SDL2 instead:

```bash
pip install --force-reinstall --no-binary pygame pygame
```

This takes several minutes on the Pi. Verify the correct SDL version afterwards:

```bash
python -c "import pygame; print(pygame.get_sdl_version())"
# Should print (2, 26, x) — the system SDL2 version, not (2, 28, x)
```

### 6. Add the user to the display device groups

KMS/DRM access requires membership of the `video` and `render` groups:

```bash
sudo usermod -a -G video,render $USER
```

Log out and back in for the group change to take effect.

### 7. Verify the data files are present

```
data/de421.bsp      ← JPL ephemeris (~17 MB, included)
data/bsc5.json      ← Yale Bright Star Catalog (included)
```

If `de421.bsp` is missing, skyfield can download it on first run (requires internet access). Place the downloaded file in the `data/` directory.

---

## Configuration

All tuneable constants live in [`config.py`](config.py). Edit them directly before deploying.

### Geographic location

```python
LOCATION_LAT  = 51.75    # decimal degrees (positive = North)
LOCATION_LON  = -0.22    # decimal degrees (positive = East)
LOCATION_ELEV = 80       # metres above sea level
```

### Serial port

By default the serial RX thread opens `/dev/ttyAMA0` (UART0 on the Pi). Override at runtime:

```bash
SERIAL_PORT=/dev/ttyS0 python main.py
```

Or change the default in `config.py`:

```python
SERIAL_PORT = "/dev/ttyAMA0"
```

### Display options

```python
SHOW_OUT_OF_SCOPE_STARS = True    # False hides stars not in any slice
SHOW_MIDI_NOTE_LABELS   = False   # True shows sounding note names in the grid
TARGET_FPS              = 30
```

### Sequencer defaults

```python
MAX_POLY_NOTES         = 5        # maximum simultaneous notes per track in poly mode
PPQN                   = 24       # MIDI clock resolution (standard)
SKY_RECALC_INTERVAL_MS = 250      # minimum ms between sky recomputations
```

---

## Enabling UART0 on the Pi

The Pi's primary UART must be freed from the Bluetooth controller and enabled for general use.

Add to `/boot/firmware/config.txt`:

```
dtoverlay=disable-bt
enable_uart=1
```

Disable the serial console:

```bash
sudo raspi-config
# → Interface Options → Serial Port
# "Would you like a login shell accessible over serial?" → No
# "Would you like the serial port hardware to be enabled?" → Yes
```

Reboot.

---

## Running

### Command-line arguments

```
python main.py [--no-gpio] [--no-serial] [--resolution WxH]
```

| Argument | Effect |
|---|---|
| `--no-gpio` | Skip the GPIO input handler. Use keyboard shortcuts instead (see [Controls](#controls)). |
| `--no-serial` | Skip the serial RX thread. All 8 tracks are initialised with built-in defaults so the sequencer produces sound without a controller attached. |
| `--resolution WxH` | Force a specific window size, e.g. `800x480` or `1920x1080`. Useful for testing layouts at different screen sizes. |

These flags are independent and can be combined:

```bash
# Full hardware
python main.py

# Pi with display + MIDI, no controller attached yet
python main.py --no-serial

# Development on a desktop machine (no GPIO, no serial)
python main.py --no-gpio --no-serial
```

### SDL video driver (automatic)

The display renderer auto-detects the SDL video driver at startup. No environment variables need to be set manually:

| Environment | Driver selected |
|---|---|
| Wayland session (`WAYLAND_DISPLAY` set) | `wayland` |
| X11 session (`DISPLAY` set) | `x11` |
| Bookworm Lite / no display server | `kmsdrm` (requires `video`/`render` group membership) |

The selected driver is logged at startup. Override by setting `SDL_VIDEODRIVER` before launching if needed.

### Foreground (development / testing)

```bash
cd ~/starseq
source .venv/bin/activate
python main.py --no-gpio --no-serial
```

### Autostart on boot (systemd)

Create `/etc/systemd/system/starseq.service`:

```ini
[Unit]
Description=starseq
After=network.target sound.target

[Service]
User=<user>
WorkingDirectory=/home/<user>/starseq
ExecStart=/home/<user>/starseq/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
SupplementaryGroups=video render audio
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

No `DISPLAY` or `SDL_VIDEODRIVER` environment variables are needed — the application detects the correct driver automatically. If the Pi boots to a desktop session, set `Environment=SDL_VIDEODRIVER=wayland` (or `x11`) explicitly to skip the auto-detection.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable starseq
sudo systemctl start starseq
```

View logs:

```bash
journalctl -u starseq -f
```

---

## Real-time scheduling (recommended)

The sequencer engine thread requests `SCHED_FIFO` priority automatically. Grant the permission without running as root:

```bash
sudo nano /etc/security/limits.d/starseq.conf
```

```
<user>  -  rtprio  99
<user>  -  memlock  unlimited
```

Log out and back in (or reboot) for this to take effect.

---

## Controls

### Physical (Raspberry Pi hardware)

| Control | Action |
|---|---|
| SPDT switch | Toggle global play / stop |
| Rotary encoder — turn | Adjust the focused parameter (BPM by default) |
| Encoder button — short press | Advance focus to the next parameter in the transport bar |
| Encoder button — hold ≥ 2 s | Reset simulated sky clock to current UTC (multiplier unchanged) |

### Keyboard (always available in the pygame window)

| Key | Action |
|---|---|
| `P` | Toggle play / stop |
| `R` | Reset simulated sky clock to current UTC |
| `Space` / `Enter` | Advance focus to the next parameter in the transport bar |
| `↑` / `↓` | Navigate parameters without changing value |
| `→` / `+` / `=` | Increase focused parameter value |
| `←` / `-` | Decrease focused parameter value |
| `Escape` | Quit |

### Parameter bar

The transport bar across the top of the window is the parameter menu — it is always visible. All global parameters are shown as labelled columns; the focused column is highlighted.

| Parameter | Range / options |
|---|---|
| Location menu | menu for location settings |
| Constalations | switch on/off |
| Planets | switch on/off |
| BPM | 20.0 – 300.0 (step 1) |
| Clock Source | internal / external |
| Key | C, C#, D … B |
| Scale | Major, Minor, Dorian, Phrygian, Lydian, Mixolydian, Locrian, Whole Tone, Pentatonic Maj, Pentatonic Min, Chromatic |
| Max Poly | 1 – 8 notes per step |
| MIDI Device | cycles through connected output ports |
| MIDI Channel mode | default, sequential, all 1 channel, self-report |
| Time Multiplier | x1, x2, x4, x8 … x64, FROZEN, and negative mirror values |
| Clock menu | menu for clock settings |
| Layout | switch between showing tracks, dimming tracks, and hiding tracks |

Changing **Key**, **Scale**, or **Max Poly** immediately triggers a sequence rebuild on all tracks. Changing **MIDI Device** reopens the MIDI output port.

---

## Display layout

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ LOC | CONST | PLNT | VIEW | PULSE | 120.0 BPM |  INT | C |  MAJ | POLY 5 | USB MIDI | MIDI CH MODE | x1 | CLK | LAYOUT | ▶ │  ← transport bar
├──────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────┤
│                                                              │  track 1 ████████████████░░░░░░░░░░░░░░░░  ▶                │
│              star dome                                       │  track 2 ████████████░░░░░░░░░░░░░░░░░░░░  ▶                │
│             (polar plot,                                     │  track 3 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ■                 │
│               N at top)                                      │  ...                                                         │
│                                                              │  track 8 ████████████████████████████████  ▶                │
└──────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────┘
```

- **Star dome**: circular polar projection; centre = zenith, edge = horizon, north at top. Track slice wedges are outlined in their track colour. Stars are coloured by which track's slice they fall in. Stars pulse briefly when a note fires from them.
- **Sequencer grid**: 8 rows (one per track); each row divided into `length` step cells. The active step is highlighted. Small dots within each cell show the notes available at that step, positioned vertically by MIDI pitch. Stale or offline controller rows are hatched.
- **Transport bar**: always-on strip showing Location menu, constellaion and planet switches, BPM, clock source, key, scale, max poly, MIDI device, time multiplier, clock controls, and play/stop icon.

---

## Simulated time multiplier

The sky engine runs on a simulated clock that can be accelerated, frozen, or reversed relative to wall-clock time. Set it via the **Time Multiplier** entry in the parameter menu.

| Multiplier | Effect |
|---|---|
| `x1` | Real time — sky matches actual UTC |
| `> x1` | Fast-forward — stars sweep faster |
| `FROZEN` | Sky locked at current simulated moment |
| Negative | Stars move backward |

Changing the multiplier only changes the rate of advance. Not the time. The **long-hold gesture** (≥ 2 s on the encoder button, or `R` on keyboard) snaps the simulated clock back to current UTC (as best as the Pi knows. With no NTP it resets to whatever the last "known" time was) without altering the multiplier.

If the simulated time drifts outside the bounds of the ephemeris data (approximately 1900–2050 for DE421), the clock is automatically reset to current UTC.

---

## Development and testing on other systems

```bash
# Windows (PowerShell)
.venv\Scripts\activate
python main.py --no-gpio --no-serial --resolution 1280x720

# macOS / Linux
source .venv/bin/activate
python main.py --no-gpio --no-serial --resolution 1280x720
```

- `--no-gpio` suppresses the `gpiozero/lgpio not available` warning and skips the idle input handler thread.
- `--no-serial` prevents errors from a missing serial port and starts all tracks in playable mono mode immediately.
- `--resolution` is recommended on desktop to get a windowed (non-fullscreen) display.
- MIDI output works via any rtmidi backend (Windows MIDI Mapper, CoreMIDI, ALSA).

---