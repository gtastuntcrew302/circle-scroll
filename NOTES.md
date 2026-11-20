# circle-scroll — development notes

## The hardware

- Laptop: Panasonic CF-SV1 (Let's note)
- Touchpad: **Synaptics TM3562-003**, I2C (`i2c-SYNA0102:00`), USB-style ID 06cb:cdea
  (KDE writes this as 1739 / 52714 in decimal), normally `/dev/input/event3`
- Sensor area about 44 × 45 mm; the round, reachable part is smaller
- Calibration (2,630 samples): centre **(22.0, 22.5) mm**, traced rim radius **16.3 mm**
- Session: KDE Plasma 6.3.6 on **X11**, using the `libinput` driver (not the old `synaptics` one)

## How it works

1. The program **grabs** the real touchpad, so only it receives the touchpad's events.
2. It creates a **virtual copy** of the touchpad (uinput, the kernel's
   "user input" device) with the *same name and IDs*, and passes normal touches
   through to it unchanged.
3. A one-finger touch that **lands on the rim** is held back briefly:
   - moves *around* the circle → becomes scrolling (never reaches the copy)
   - moves *inward* → sent to the copy as a normal touch where the finger is now
   - lifts without moving (a tap) → sent to the copy as a tap
4. Scrolling is done by a second, hidden virtual touchpad, **"Circle scroll
   touchpad"**, which fakes a two-finger vertical drag. Apps treat it exactly like
   real two-finger scrolling.

Why not the old X11 `synaptics` driver, which has `CircularScrolling` built in?
- KDE Plasma 6's touchpad settings page no longer supports that driver
- its "edge" zones are rectangular, so on a round pad they only trigger near
  the top, bottom, left and right
- it doesn't work on Wayland

## Problems hit along the way (and the fixes)

### "No touchpad found" on the first calibration
python-evdev's `capabilities()` returns axis details by default, so checking
whether `ABS_X` was in the list never matched. Fixed with `capabilities(absinfo=False)`.
The test fake didn't copy this behaviour; it does now.

### Pointer very slow with circle-scroll running
Two causes:
1. **Settings didn't carry over.** KDE's touchpad module applies
   `~/.config/touchpadxlibinputrc` (pointer speed **0.6**) once at login, to the
   real touchpad only. The virtual copy appears later and stays at the default **0.0**.
   - Giving the copy the same name was *not* enough on X11.
   - Fixed by hand for testing: `xinput set-prop <copy id> "libinput Accel Speed" 0.6`
   - Made automatic with `circle-scroll-xsync.py` (see below).
   - Note: `~/.config/kcminputrc` also says 0.4 for this touchpad, but the value actually
     in use is 0.6, from `touchpadxlibinputrc`.
2. **"Touch jump detected and discarded"** in `/var/log/Xorg.0.log`. A rim touch that
   turned into pointer movement was being replayed as a burst of events microseconds
   apart, and libinput threw it away as a glitch. Fixed by sending one clean
   touch-down at the finger's current position instead.

### Scrolling "notchy"
- First version used mouse-wheel events, which apps treat as steps.
  Switched to faking two-finger scrolling.
- Renamed the scroll device to include "touchpad", because Qt (KDE apps) looks for
  "touchpad"/"synaptics" in the name to decide whether something is a touchpad.
- Measured with `xinput test-xi2 --root` (15 units = one wheel click):

  | Source | Scroll events | Typical step |
  |---|---|---|
  | Real two-finger scroll | 604 | 10.5 |
  | Circle scroll | 1,002 | 4.2 |

  Circle scroll is now *finer* than real two-finger scrolling, and the owner
  confirmed real two-finger scrolling has the same notches. **Remaining
  notchiness is the apps on X11** rounding to whole lines.
  A Plasma **Wayland** session would give true pixel scrolling (not tried yet).

## Speed math (scroll_style "touchpad")

libinput turns 1 mm of two-finger movement into about
`1000/25.4 × 0.9 × 0.2968 ≈ 10.5` scroll units, and X counts 15 units as one
wheel click. So one click ≈ **1.43 mm** of fake finger travel, and
`degrees_per_notch` (20°) of circling = one click. The owner rated 20° "perfect".

## Useful commands

```
xinput list --short                       # list devices + ids
xinput list-props <id>                    # show a device's settings
command grep -i -E 'circle|TM3562|jump' /var/log/Xorg.0.log   # what the X server said
```

## System Settings page + service (2026-11-20)

- Page: `kcm/` (C++ `KQuickConfigModule` + `ui/main.qml`), category `pointing-devices`
  (the same group as KDE's Mouse and Touchpad pages). It only writes `~/.config/circlescrollrc`.
- The root service (`/etc/systemd/system/circle-scroll.service`) checks that file about once a second, so
  no password prompt. Off = lets go of the touchpad and removes the virtual devices.
  Speed/direction apply live; on/off and smooth/wheel restart the session.
- Status for the page: `/run/circle-scroll/status` (`on` / `off` / `no-touchpad`); systemd's
  `RuntimeDirectory` deletes it when the service stops, which the page shows as "not running".
- The service runs a root-owned copy in `/usr/local/bin`, never the file in ~/Documents.
  Re-run `sudo ./install.sh` after editing.
- Gotcha during install: a leftover manual test copy still held the touchpad, so the service
  crash-looped (grab busy) until that copy was stopped. Only one copy can run at a time.
  Now handled: the service logs a clear message, sets status `busy` (shown on the page), and retries.
- Settings-copy helper starts from `/etc/xdg/autostart/` at login (X11 only), and was tested live by
  setting the copy's speed back to 0.0. It also copies "Device Enabled", so turning the touchpad off with
  KDE's touchpad key should still work (not tested yet).

## Packaging for other people (2026-11-20, v1.0.0)

- `install.sh` does everything: installs missing packages (apt prompts), builds the settings page
  as the invoking user (so `kcm/build` isn't root-owned), installs the files, and **restarts** the
  service. Plain `enable --now` would leave an already-running old version going after an update.
- `circle-scroll.json` holds the CF-SV1 calibration and is installed only if `/etc/circle-scroll.json`
  doesn't exist yet, so updates never overwrite someone's own calibration.
- The service reads one user's `~/.config/circlescrollrc` (whoever ran `sudo ./install.sh`).
  Fine for a single-user laptop; another account would get the defaults.
- After an update, the running settings-copy helper keeps its old code until the next login.
- Wayland: untested. Expected to work (KWin applies touchpad settings to the same-named copy;
  the helper exits on Wayland). It would also give pixel-smooth scrolling in Qt apps.
