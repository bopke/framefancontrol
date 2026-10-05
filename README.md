# framefancontrol

Cap the fan speed of a **Steam Frame**, with a slider right in the headset's
**Quick Access → Performance** tab.

I wrote this because at full speed the Frame's fan pushes enough air past the
face gasket that I could feel a draft on my eyes. Until the seal is fixed, I'd
rather have the headset throttle a little than blow air into my eyes. If you'd
like a quieter or gentler fan and can accept some throttling, this is for you.

- **Fan Cap slider** in Quick Access → Performance, just above *Common Settings*.
  It shows the live hottest temperature and fan RPM, so you can tune the trade-off
  while playing.
- **Changes apply within a second.** No restart, no password once installed.
- **Works with Valve's fan controller, not against it.** Valve's temperature curve
  stays in charge; only the maximum speed is lowered.
- **Survives reboots and SteamOS updates.** It falls back to Valve's stock
  behaviour if anything it relies on changes.

> **Unofficial.** Not affiliated with or endorsed by Valve. It changes how your
> headset is cooled, so use it at your own risk. See [Safety](#safety).

## How it works

The Frame's fan (`slg4ax46073v`, `pwm1` = 0–100 % duty) is driven by Valve's
`deckard-fan-control` service. It follows a temperature curve and never goes above
`fan_max_speed`, which is **55 % duty (~5,500 rpm)** in the stock config.

framefancontrol does three things:

1. **Fan service:** a systemd drop-in makes `deckard-fan-control` start through
   `framefan.py`. This loads Valve's own controller and config, lowers only
   `fan_max_speed`, and runs it. The cap is read from `/etc/framefan/cap` every
   second. If anything unexpected happens, for example a SteamOS update changes
   Valve's code, it runs Valve's controller unmodified.
2. **Slider:** a small user service (`framefan_qam.py`) adds the slider to Steam's
   Quick Access menu through Steam's local UI debugging port, which Developer Mode
   opens on `127.0.0.1:8080`. The slider is built from Steam's own slider row, so it
   looks and behaves like the native ones. Moving it writes the new value to
   `/etc/framefan/cap`.
3. **Installer:** `frame.sh` runs on your computer and does the installing over SSH.

### What the percentage means

The cap is a **percentage of Valve's stock top speed**:

| Cap | Max fan duty | ≈ Max RPM |
|----:|-------------:|----------:|
| 100 % | 55 % (stock) | 5,500 |
| 90 % | 49 % | 4,900 |
| 85 % | 46 % | 4,600 |
| 70 % | 38 % | 3,800 |
| 55 % (lowest) | 30 % | 3,000 |

55 % is the lowest allowed value because it equals the fan's idle speed. A lower
cap would sit below the speed the fan runs at when the headset is cool.

## Requirements

- A Steam Frame with **Developer Mode** enabled (instructions below).
- A computer on the same network with `bash`, `ssh` and `scp`. macOS and Linux work
  out of the box. On Windows, use WSL.

## Installation

### 1. Enable Developer Mode and SSH on the Frame

1. In the headset, open **Steam Settings → System** and turn on **Enable Developer Mode**.
2. In the new **Developer** section, choose **Set User Password** and pick a
   password. SSH uses it, and so does `sudo` during installation.
3. Find the headset's IP address in its **Wi‑Fi settings**, e.g. `192.168.1.50`.

### 2. Set up SSH key login from your computer

```sh
ssh-copy-id steamos@192.168.1.50      # use your Frame's IP; asks for the password once
ssh steamos@192.168.1.50 true         # should now connect without asking
```

If `ssh-copy-id` says there's no key, create one first with `ssh-keygen -t ed25519`.

### 3. Install

```sh
git clone https://github.com/bopke/framefancontrol.git
cd framefancontrol
export FRAME=steamos@192.168.1.50     # your Frame's IP
./frame.sh install 85                 # starting cap; asks for the Developer Mode password
```

The installer checks the value first. Then it installs the fan service, starts the
slider and prints the current fan status. Tip: setting a DHCP reservation for the
headset in your router keeps the IP from changing.

### 4. Use it

Put the headset on, open **Quick Access** and go to the **Performance** tab. The
**Fan** section is just above *Common Settings*:

- **Drag the slider with the laser.** The value is saved when you let go and applied
  within about a second.
- **The row shows the hottest sensor temperature**, and the section header shows the
  fan's current RPM.
- **Tune while playing.** Start around 85 %. If temperatures climb into the
  mid-90s °C, the chip is throttling; raise the cap a little.

The slider responds to the laser pointer, but controller navigation (D‑pad or
thumbsticks) skips over it.

## Commands

All commands run on your computer and need `FRAME` to be set.

| Command | What it does |
|---|---|
| `./frame.sh install 85` | Install everything and set the cap to 85 %. Needs the sudo password. Run again to update. |
| `./frame.sh set 70` | Set the cap from your computer, same as moving the slider. |
| `./frame.sh status` | Fan duty, RPM, active cap and hottest sensor. |
| `./frame.sh watch` | The same, refreshed every second (Ctrl‑C to quit). |
| `./frame.sh slider` | Reinstall or update just the slider (no sudo needed). |
| `./frame.sh log` | Follow the fan service log. Shows each cap change. |
| `./frame.sh uninstall` | Remove everything and go back to stock. Needs the sudo password. |

## Safety

- **Overheat protection is not affected.** The CPU and GPU still slow themselves
  down as they get hot, and the hardware's critical-temperature shutdown still
  works. framefancontrol only limits the fan, so a capped headset throttles sooner
  instead of spinning faster.
- **Valve's overheat behaviour stays.** If a sensor passes 95 °C, Valve's controller
  still runs the fan at its maximum, which is now your cap.
- **The fan can't be set below idle.** The service ignores any cap outside
  55–100 %, wherever the value came from.
- **Failures fall back to stock.** If the capped controller can't start, Valve's
  original controller runs instead. Uninstalling restores the stock setup fully.
- **Permissions stay tight.** The fan service code is owned by root, in
  `/etc/framefan/`. Only the cap value file can be written by the `steamos` user,
  which is what lets the slider work without sudo.

## What gets installed

| On the headset | Purpose |
|---|---|
| `/etc/framefan/framefan.py` | Fan service launcher (root-owned) |
| `/etc/framefan/cap` | Current cap, e.g. `85` (writable by `steamos`) |
| `/etc/systemd/system/deckard-fan-control.service.d/framefan.conf` | Points Valve's fan service at the launcher |
| `~/.local/share/framefan/framefan_qam.py` | Quick Access slider |
| `~/.config/systemd/user/framefan-qam.service` | Starts the slider with the VR session |
| `~/framefan.py`, `~/framefan_qam.py` | Working copies used by `status`/`set`/`watch` |

Everything lives in `/etc` or your home directory, and SteamOS keeps both across
OS updates. The read-only system image is never modified.

## Troubleshooting

- **"Set your headset's address first"**: run `export FRAME=steamos@<your Frame's IP>`
  in the terminal you're using.
- **`ssh: connect … timed out`**: the headset is asleep, off, or on a different
  IP. Wake it up and check the IP in its Wi‑Fi settings.
- **The slider doesn't show up**: check that Developer Mode is still on, then run
  `./frame.sh slider`. If a Steam update changed the Quick Access menu, the slider
  can disappear while the cap itself keeps working. Use `./frame.sh set` until it's
  fixed, and please open an issue.
- **Is the cap active?** Run `./frame.sh status`. It says `framefan active` when the
  capped controller is running, and `./frame.sh log` shows each cap change.

## Tested with

- Steam Frame, SteamOS (Linux 6.18), `deckard-fan-control` 20260324.1-2, October 2026.
