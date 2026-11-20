# circle-scroll

iPod-style circular scrolling for the round touchpad on the **Panasonic CF-SV1**
(Let's note), on Debian 13 with KDE Plasma 6.

Put one finger on the **outer rim** of the touchpad and run it around the circle:

- **clockwise** → scroll down
- **counter-clockwise** → scroll up

Everything else works as normal: pointer movement, tapping, two-finger
scrolling, the buttons, and touches that start on the rim and then move inward.
This brings back the circular scrolling that Panasonic's Windows touchpad driver had.

It comes with an on/off switch in **System Settings → Mouse & Touchpad → Circle Scroll**.

## Requirements

| | Tested on |
|---|---|
| Laptop | Panasonic CF-SV1 (touchpad: Synaptics TM3562-003, round) |
| System | Debian 13 "trixie", KDE Plasma 6.3, **X11** session |
| Wayland | Should work, but not tested yet |

Other touchpads should work after a one-time calibration (see below), but
only the CF-SV1 has been tried.

## Install

1. Get the files, either way works:
   - **With git:**
     ```
     git clone https://github.com/gtastuntcrew302/circle-scroll
     cd circle-scroll
     ```
     (`git clone` downloads the project; `cd` = "change directory" moves into it.)
   - **Without git:** on the GitHub page click **Code → Download ZIP**, extract it,
     then right-click the extracted folder → **Open Terminal Here**.
2. Run:

   ```
   sudo sh install.sh
   ```

   - `sudo` ("superuser do") runs it as administrator; it will ask for your password
   - `sh` ("shell") runs the install script

   The script lists any Debian packages it needs and **apt asks before installing
   them** (about 90 packages the first time, mostly the KDE/Qt files needed to
   build the settings page). Then it builds and installs everything and starts the
   service.
3. **Log out and log back in once**, so your touchpad settings (pointer speed and so on)
   are applied while circle-scroll is running.

That's it. Circle scrolling is on, and it starts automatically at every boot.

To **update** to a newer version, run `sudo sh install.sh` again from the new folder
(with git: `git pull` first, which downloads the latest changes).
It keeps your settings.

## Using it

**System Settings → Mouse & Touchpad → Circle Scroll**

- **Enable**: on/off. When it's off, the touchpad is left completely alone.
- **Scroll speed**: how far you circle for each scroll step
- **Clockwise scrolls down**: flip the direction
- **Smooth scrolling**: smooth (like two-finger scrolling) or mouse-wheel steps

Press **Apply**; changes take effect within about a second. No password is needed.
The box at the bottom shows whether the background service is running.

## Calibrating (other laptops, or if the rim feels off)

The install includes the CF-SV1's measurements. To measure your own touchpad:

```
sudo systemctl stop circle-scroll
sudo python3 circle-scroll.py --calibrate --seconds 20
sudo systemctl start circle-scroll
```

- `systemctl` ("system control") stops and starts background services
- `--calibrate` records your finger. Right after entering your password, run **one finger**
  slowly around the **very edge** of the touchpad, over and over, for the full 20 seconds.
  The pointer won't move during this; that's expected.

It saves the result to `/etc/circle-scroll.json`.

## Uninstall

```
sudo sh uninstall.sh
```

This removes everything except your settings files (`/etc/circle-scroll.json` and
`~/.config/circlescrollrc`). The touchpad goes straight back to normal. The build
packages stay installed. They're only needed for building, so you can remove them
with apt if you like.

## Troubleshooting

| Problem | What to do |
|---|---|
| Settings page says the service is **not running** | `sudo systemctl status circle-scroll`, and `sudo journalctl -u circle-scroll -n 30` for its last 30 log lines (`-u` = unit, `-n` = number of lines) |
| Page says **another program is holding the touchpad** | A test copy (`circle-scroll.py` started by hand in a terminal) is still running. Press Ctrl+C in that terminal. |
| **Pointer feels slow** while circle-scroll is on | Log out and back in once (starts the settings-copy helper) |
| Scrolling in KDE apps moves in **line-sized steps** | That's how many apps handle any touchpad scrolling on X11; real two-finger scrolling does the same. A Plasma Wayland session should be smoother. |
| Rim too wide/narrow, or scrolling starts by accident | Recalibrate (above), or adjust `rim_fraction` in `/etc/circle-scroll.json` |

If circle-scroll ever stops or crashes, the touchpad instantly works normally again.

## Advanced settings (`/etc/circle-scroll.json`)

Edit with `sudo nano /etc/circle-scroll.json`, then `sudo systemctl restart circle-scroll`.

| Key | Default | Meaning |
|---|---|---|
| `rim_fraction` | `0.72` | How close to the edge a touch must land to count as "rim". Higher = thinner rim zone. |
| `trigger_mm` | `2.5` | How far (mm) a rim touch moves before deciding "scroll" or "pointer" |
| `center_x_mm`, `center_y_mm`, `radius_mm` | CF-SV1 values | Where the circle is (set by `--calibrate`) |
| `device_name` | `""` | Part of the touchpad's name, if auto-detect picks the wrong device (`sudo python3 circle-scroll.py --list`) |
| `degrees_per_notch`, `clockwise_scrolls_down`, `scroll_style` | | Used only if the System Settings page has never been saved |

## How it works (short version)

A small service takes over the touchpad and creates a **virtual copy** of it.
Normal touches are passed through to the copy unchanged. A one-finger touch that
lands on the rim and moves **around** the circle becomes scrolling instead.
Scrolling is done by faking a two-finger scroll on a second, hidden virtual
touchpad, so apps scroll it exactly like real two-finger scrolling.

The full story, including the problems hit along the way and how they were solved,
is in [NOTES.md](NOTES.md).

## Files

| Path | What it is |
|---|---|
| `circle-scroll.py` | The service (Python + python3-evdev); runs as root |
| `circle-scroll-xsync.py` | Copies your touchpad settings onto the virtual copy (X11 only; runs in your session) |
| `circle-scroll.json` | Default settings with the CF-SV1 calibration |
| `kcm/` | The System Settings page (C++ and QML) |
| `install.sh`, `uninstall.sh` | Install/update, and remove |
| `tests/test_logic.py` | Simulated-touch tests: `python3 -I tests/test_logic.py` |
| `NOTES.md` | Development notes |
| `VERSION` | Version number |
| `LICENSE` | MIT license |

## License

MIT. See [LICENSE](LICENSE).
