#!/usr/bin/env python3
"""circle-scroll: iPod-style circular scrolling for round touchpads.

Made for the Panasonic CF-SV1 (Synaptics TM3562 circular pad), but works with
any touchpad.

How it works:
  * The real touchpad is grabbed exclusively, and a virtual copy of it (same
    name, so KDE applies your existing touchpad settings) is created with
    uinput.  Normal touches are passed through to the copy unchanged, so
    tap-to-click, two-finger scroll, palm detection etc. keep working.
  * When ONE finger lands on the outer rim of the pad and then moves AROUND the
    circle, the touch is not passed through.  Its rotation is turned into
    scrolling instead.  Clockwise = scroll down, counter-clockwise = scroll up.
  * Scrolling is done by faking a two-finger scroll on a second, invisible
    virtual touchpad, so apps scroll it exactly as smoothly as a real
    two-finger scroll.  (Set "scroll_style": "wheel" for mouse-wheel steps.)
  * If a rim touch moves inward instead, or is just a tap, it is handed to the
    virtual touchpad as a normal touch, so pointer movement and tapping work.

Usage:
  circle-scroll --list         show input devices
  circle-scroll --calibrate    trace the rim a few times; saves the pad's circle
  circle-scroll                run (needs root, normally via systemd)
  circle-scroll --user-config ~/.config/circlescrollrc
                               ...and follow the System Settings page's on/off switch
"""

import argparse
import configparser
import errno
import json
import math
import os
import select
import sys
import time

import evdev
from evdev import ecodes as e, AbsInfo

CONFIG_PATH = "/etc/circle-scroll.json"
PHYS_TAG = "circle-scroll"          # marks our own virtual devices
STATUS_PATH = "/run/circle-scroll/status"

DEFAULTS = {
    "device_name": "",          # substring of the touchpad name; "" = auto-detect
    "center_x_mm": None,        # filled in by --calibrate
    "center_y_mm": None,
    "radius_mm": None,          # radius of the path traced along the rim
    "rim_fraction": 0.72,       # touch must land at >= this fraction of radius
    "degrees_per_notch": 20.0,  # rotation per mouse-wheel "click" (smaller = faster)
    "trigger_mm": 2.5,          # movement before deciding scroll vs. pointer
    "clockwise_scrolls_down": True,
    "scroll_style": "touchpad", # "touchpad" = smooth, "wheel" = mouse-wheel steps
    "enabled": True,            # normally set from the System Settings page
}

BUTTONS = {e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE}
FINGER_TOOLS = {
    e.BTN_TOOL_FINGER: 1, e.BTN_TOOL_DOUBLETAP: 2, e.BTN_TOOL_TRIPLETAP: 3,
    e.BTN_TOOL_QUADTAP: 4, e.BTN_TOOL_QUINTTAP: 5,
}
MT_CODES = set(range(e.ABS_MT_TOUCH_MAJOR, e.ABS_MT_TOOL_Y + 1)) - {e.ABS_MT_SLOT}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def load_config(path):
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


def is_ours(dev):
    return (dev.phys or "").startswith(PHYS_TAG) or dev.name.endswith("(circle-scroll)")


def is_touchpad(dev):
    caps = dev.capabilities(absinfo=False)
    abs_codes = caps.get(e.EV_ABS, [])
    key_codes = caps.get(e.EV_KEY, [])
    return (e.ABS_X in abs_codes and e.BTN_TOOL_FINGER in key_codes
            and e.INPUT_PROP_DIRECT not in dev.input_props())


def find_touchpad(name_hint):
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        if is_ours(dev):
            dev.close()
            continue
        if name_hint and name_hint.lower() in dev.name.lower():
            return dev
        if not name_hint and is_touchpad(dev):
            return dev
        dev.close()
    return None


class Geometry:
    """Converts raw touchpad units to millimetres."""

    def __init__(self, dev):
        self.ax = dev.absinfo(e.ABS_X)
        self.ay = dev.absinfo(e.ABS_Y)
        # Fall back to a guess if the device reports no resolution.
        self.rx = self.ax.resolution or max(1, (self.ax.max - self.ax.min) / 60)
        self.ry = self.ay.resolution or max(1, (self.ay.max - self.ay.min) / 60)

    def mm(self, x, y):
        return (x - self.ax.min) / self.rx, (y - self.ay.min) / self.ry

    def size_mm(self):
        return (self.ax.max - self.ax.min) / self.rx, (self.ay.max - self.ay.min) / self.ry


def angle_diff(a, b):
    """Smallest signed difference a - b, in radians."""
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


class DeviceModel:
    """Tracks the real touchpad's current state from its event stream."""

    def __init__(self, dev):
        self.keys = {}
        self.abs = {}
        self.slot = 0
        self.mt = {}
        caps = dev.capabilities(absinfo=True)
        for code in caps.get(e.EV_KEY, []):
            self.keys[code] = 0
        for code, info in caps.get(e.EV_ABS, []):
            if code == e.ABS_MT_SLOT:
                self.slot = info.value
                for s in range(info.min, info.max + 1):
                    self.mt[s] = {e.ABS_MT_TRACKING_ID: -1}
            elif code not in MT_CODES:
                self.abs[code] = info.value
        if not self.mt:
            self.mt[0] = {e.ABS_MT_TRACKING_ID: -1}

    def apply(self, frame):
        for etype, code, value in frame:
            if etype == e.EV_KEY:
                self.keys[code] = value
            elif etype == e.EV_ABS:
                if code == e.ABS_MT_SLOT:
                    self.slot = value
                    self.mt.setdefault(value, {e.ABS_MT_TRACKING_ID: -1})
                elif code in MT_CODES:
                    self.mt.setdefault(self.slot, {})[code] = value
                else:
                    self.abs[code] = value

    def touching(self):
        if self.keys.get(e.BTN_TOUCH, 0):
            return True
        return any(s.get(e.ABS_MT_TRACKING_ID, -1) != -1 for s in self.mt.values())

    def fingers(self):
        tools = max((n for code, n in FINGER_TOOLS.items() if self.keys.get(code, 0)), default=0)
        slots = sum(1 for s in self.mt.values() if s.get(e.ABS_MT_TRACKING_ID, -1) != -1)
        return max(tools, slots)

    def buttons_down(self):
        return any(self.keys.get(b, 0) for b in BUTTONS)

    def position(self):
        return self.abs.get(e.ABS_X, 0), self.abs.get(e.ABS_Y, 0)

    def full_state(self):
        """The whole current state as events.  Writing these to the virtual
        touchpad makes it match the real one exactly (the kernel drops values
        that haven't changed)."""
        out = []
        for s in sorted(self.mt):
            out.append((e.EV_ABS, e.ABS_MT_SLOT, s))
            for code, value in sorted(self.mt[s].items()):
                out.append((e.EV_ABS, code, value))
        if len(self.mt) > 1:
            out.append((e.EV_ABS, e.ABS_MT_SLOT, self.slot))
        for code, value in sorted(self.abs.items()):
            out.append((e.EV_ABS, code, value))
        for code, value in sorted(self.keys.items()):
            out.append((e.EV_KEY, code, value))
        return out


class CircleScroller:
    IDLE, FORWARD, PENDING, SCROLL = "idle", "forward", "pending", "scroll"

    def __init__(self, cfg, geom, model, pad_out, scroll_out, debug=False):
        self.cfg = cfg
        self.geom = geom
        self.model = model
        self.pad_out = pad_out        # callable(events): write + SYN to virtual pad
        self.scroll_out = scroll_out  # object with move(notches_down) and end()
        self.debug = debug
        self.state = self.IDLE
        self.snapshot = None
        self.start_mm = None
        self.last_angle = None
        sx, sy = geom.size_mm()
        self.cx = cfg["center_x_mm"] if cfg["center_x_mm"] is not None else sx / 2
        self.cy = cfg["center_y_mm"] if cfg["center_y_mm"] is not None else sy / 2
        self.r = cfg["radius_mm"] if cfg["radius_mm"] is not None else min(sx, sy) / 2 * 0.9

    def set_state(self, s):
        if self.debug and s != self.state:
            log(f"state {self.state} -> {s}")
        self.state = s

    def polar(self):
        x, y = self.geom.mm(*self.model.position())
        dx, dy = x - self.cx, y - self.cy
        # Screen y points down, so increasing atan2 means clockwise.
        return (x, y), math.hypot(dx, dy), math.atan2(dy, dx)

    def on_rim(self):
        _, dist, _ = self.polar()
        return dist >= self.r * self.cfg["rim_fraction"]

    def write_state(self, frame):
        """Bring the virtual pad fully up to date in one report (plus any
        MSC events, e.g. hardware timestamps, from the current frame)."""
        self.pad_out(self.model.full_state() + [ev for ev in frame if ev[0] == e.EV_MSC])

    def scroll_by(self, dtheta):
        notches = math.degrees(dtheta) / self.cfg["degrees_per_notch"]
        if not self.cfg["clockwise_scrolls_down"]:
            notches = -notches
        self.scroll_out.move(notches)

    def handle_frame(self, frame):
        self.model.apply(frame)
        touching = self.model.touching()
        fingers = self.model.fingers()

        if self.state == self.IDLE:
            if (touching and fingers <= 1 and not self.model.buttons_down()
                    and self.on_rim()):
                self.set_state(self.PENDING)
                self.snapshot = self.model.full_state()
                self.start_mm, _, self.last_angle = self.polar()
            else:
                # Full state rather than just the frame: re-syncs the virtual
                # pad after touches that were swallowed for scrolling.
                self.write_state(frame)
                if touching or self.model.buttons_down():
                    self.set_state(self.FORWARD)
            return

        if self.state == self.FORWARD:
            self.pad_out(frame)
            if not touching and not self.model.buttons_down():
                self.set_state(self.IDLE)
            return

        if self.state == self.PENDING:
            if not touching:
                # It was a tap: touch down where it was, then lift.
                self.pad_out(self.snapshot)
                self.write_state(frame)
                self.set_state(self.IDLE)
                return
            if fingers > 1 or self.model.buttons_down():
                self.write_state(frame)       # multi-finger gesture / click
                self.set_state(self.FORWARD)
                return
            self.snapshot = self.model.full_state()
            (x, y), dist, ang = self.polar()
            mx, my = x - self.start_mm[0], y - self.start_mm[1]
            if math.hypot(mx, my) < self.cfg["trigger_mm"]:
                return
            # Split the movement into "around the circle" and "toward the centre".
            sx, sy = self.start_mm[0] - self.cx, self.start_mm[1] - self.cy
            sd = math.hypot(sx, sy) or 1.0
            radial = abs((mx * sx + my * sy) / sd)
            tangential = abs((-mx * sy + my * sx) / sd)
            if tangential > radial:
                self.set_state(self.SCROLL)
                self.snapshot = None
                self.scroll_by(angle_diff(ang, self.last_angle))
                self.last_angle = ang
            else:
                # Moving inward: a normal touch that started on the rim.
                # Sent as one clean touch-down at the current position.
                self.write_state(frame)
                self.set_state(self.FORWARD)
            return

        if self.state == self.SCROLL:
            # Physical buttons still work while scrolling.
            buttons = [ev for ev in frame if ev[0] == e.EV_KEY and ev[1] in BUTTONS]
            if buttons:
                self.pad_out(buttons)
            if not touching:
                self.scroll_out.end()
                self.set_state(self.IDLE)
                return
            _, dist, ang = self.polar()
            if dist < self.r * 0.25:
                self.last_angle = ang     # too close to the centre: angle is jumpy
                return
            self.scroll_by(angle_diff(ang, self.last_angle))
            self.last_angle = ang


class TouchpadScroll:
    """Scrolls by faking a vertical two-finger drag on an invisible touchpad.

    It is very tall (4 m) so a scroll never has to lift and re-place its
    fingers.  Speed: libinput turns 1 mm of two-finger movement into
    25.4/1000 * 1000 * 0.9 * 0.2968 ~= 10.5 scroll units, and X counts 15
    units as one wheel click, so one wheel click ~= 1.43 mm.
    """
    RES = 40                    # units per mm
    W_MM, H_MM = 100, 4000
    MM_PER_NOTCH = 15 / (1000 / 25.4 * 0.9 * 0.2968)
    FINGER_GAP_MM = 15
    MIN_HOLD_S = 0.25           # never lift sooner, so it can't count as a tap

    def __init__(self, debug=False):
        self.debug = debug
        w, h = self.W_MM * self.RES, self.H_MM * self.RES
        caps = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_TOUCH,
                       e.BTN_TOOL_FINGER, e.BTN_TOOL_DOUBLETAP],
            e.EV_ABS: [
                (e.ABS_X, AbsInfo(0, 0, w, 0, 0, self.RES)),
                (e.ABS_Y, AbsInfo(0, 0, h, 0, 0, self.RES)),
                (e.ABS_MT_SLOT, AbsInfo(0, 0, 1, 0, 0, 0)),
                (e.ABS_MT_TRACKING_ID, AbsInfo(0, 0, 65535, 0, 0, 0)),
                (e.ABS_MT_POSITION_X, AbsInfo(0, 0, w, 0, 0, self.RES)),
                (e.ABS_MT_POSITION_Y, AbsInfo(0, 0, h, 0, 0, self.RES)),
            ],
        }
        # Bus I2C so libinput treats it as a built-in touchpad.
        self.ui = evdev.UInput(caps, name="Circle scroll touchpad", phys=PHYS_TAG + "/scroll",
                               bustype=e.BUS_I2C, vendor=0x0001, product=0x0001,
                               input_props=[e.INPUT_PROP_POINTER])
        self.xs = (w // 2 - self.FINGER_GAP_MM * self.RES // 2,
                   w // 2 + self.FINGER_GAP_MM * self.RES // 2)
        self.down = False
        self.y = 0.0
        self.written_y = None
        self.tid = 0
        self.down_since = 0.0

    def _write(self, events):
        for ev in events:
            self.ui.write(*ev)
        self.ui.syn()

    def _place(self):
        self.y = self.H_MM * self.RES / 2
        self.written_y = int(round(self.y))
        events = []
        for slot, x in enumerate(self.xs):
            self.tid = (self.tid + 1) % 65536
            events += [(e.EV_ABS, e.ABS_MT_SLOT, slot),
                       (e.EV_ABS, e.ABS_MT_TRACKING_ID, self.tid),
                       (e.EV_ABS, e.ABS_MT_POSITION_X, x),
                       (e.EV_ABS, e.ABS_MT_POSITION_Y, self.written_y)]
        events += [(e.EV_ABS, e.ABS_X, self.xs[0]), (e.EV_ABS, e.ABS_Y, self.written_y),
                   (e.EV_KEY, e.BTN_TOUCH, 1), (e.EV_KEY, e.BTN_TOOL_DOUBLETAP, 1)]
        self._write(events)
        self.down = True
        self.down_since = time.monotonic()

    def _lift(self):
        self._write([(e.EV_ABS, e.ABS_MT_SLOT, 0), (e.EV_ABS, e.ABS_MT_TRACKING_ID, -1),
                     (e.EV_ABS, e.ABS_MT_SLOT, 1), (e.EV_ABS, e.ABS_MT_TRACKING_ID, -1),
                     (e.EV_KEY, e.BTN_TOUCH, 0), (e.EV_KEY, e.BTN_TOOL_DOUBLETAP, 0)])
        self.down = False

    def move(self, notches_down):
        if not self.down:
            self._place()
        self.y += notches_down * self.MM_PER_NOTCH * self.RES
        y = int(round(self.y))
        if not 0 < y < self.H_MM * self.RES:      # ran off the end: start again
            self._lift()
            self._place()
            return
        if y == self.written_y:
            return
        self.written_y = y
        self._write([(e.EV_ABS, e.ABS_MT_SLOT, 0), (e.EV_ABS, e.ABS_MT_POSITION_Y, y),
                     (e.EV_ABS, e.ABS_MT_SLOT, 1), (e.EV_ABS, e.ABS_MT_POSITION_Y, y),
                     (e.EV_ABS, e.ABS_Y, y)])
        if self.debug:
            log(f"scroll {notches_down:+.2f} notches")

    def end(self):
        if not self.down:
            return
        wait = self.MIN_HOLD_S - (time.monotonic() - self.down_since)
        if wait > 0:
            time.sleep(wait)
        self._lift()

    def close(self):
        if self.down:
            self._lift()
        self.ui.close()


class WheelScroll:
    """Scrolls with mouse-wheel events (hi-res where supported)."""

    def __init__(self, debug=False):
        self.debug = debug
        caps = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_WHEEL_HI_RES],
        }
        # BUS_VIRTUAL so KDE doesn't treat it as an external mouse (which can
        # trigger "disable touchpad when a mouse is plugged in").
        self.ui = evdev.UInput(caps, name="Circle scroll wheel", phys=PHYS_TAG + "/wheel",
                               bustype=e.BUS_VIRTUAL)
        self.acc = 0.0
        self.sent = 0

    def move(self, notches_down):
        self.acc += -notches_down * 120        # wheel: positive = up
        delta = int(self.acc)
        if delta == 0:
            return
        self.acc -= delta
        before = self.sent
        self.sent += delta
        notches = int(self.sent / 120) - int(before / 120)
        self.ui.write(e.EV_REL, e.REL_WHEEL_HI_RES, delta)
        if notches:
            self.ui.write(e.EV_REL, e.REL_WHEEL, notches)
        self.ui.syn()
        if self.debug:
            log(f"wheel hires={delta} notches={notches}")

    def end(self):
        self.acc = 0.0

    def close(self):
        self.ui.close()


def make_virtual_pad(dev):
    caps = dev.capabilities(absinfo=True)
    caps.pop(e.EV_SYN, None)
    caps.pop(e.EV_FF, None)
    # Same name/IDs as the real pad, so KDE applies your touchpad settings.
    return evdev.UInput(caps, name=dev.name, phys=PHYS_TAG + "/pad",
                        vendor=dev.info.vendor, product=dev.info.product,
                        version=dev.info.version, bustype=dev.info.bustype,
                        input_props=dev.input_props())


class UserSettings:
    """The on/off switch and preferences saved by the System Settings page
    (~/.config/circlescrollrc, KDE's INI-style format).  Checked about once a
    second, so changes apply without restarting anything."""

    def __init__(self, path):
        self.path = path
        self.mtime = None
        self.last_check = 0.0

    def _stat(self):
        try:
            return os.stat(self.path).st_mtime_ns
        except (OSError, TypeError):
            return None

    def load(self):
        self.mtime = self._stat()
        if not self.path:
            return {}
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        try:
            cp.read(self.path)
        except configparser.Error as err:
            log(f"Ignoring unreadable {self.path}: {err}")
            return {}
        if not cp.has_section("General"):
            return {}
        g = cp["General"]

        def flag(key):
            return g[key].strip().lower() in ("true", "1", "yes", "on")

        out = {}
        if "Enabled" in g:
            out["enabled"] = flag("Enabled")
        if "ClockwiseScrollsDown" in g:
            out["clockwise_scrolls_down"] = flag("ClockwiseScrollsDown")
        if "SmoothScrolling" in g:
            out["scroll_style"] = "touchpad" if flag("SmoothScrolling") else "wheel"
        if "DegreesPerNotch" in g:
            try:
                out["degrees_per_notch"] = min(90.0, max(4.0, float(g["DegreesPerNotch"])))
            except ValueError:
                pass
        return out

    def changed(self):
        now = time.monotonic()
        if now - self.last_check < 1.0:
            return False
        self.last_check = now
        return self._stat() != self.mtime


def write_status(text):
    """Status for the System Settings page (systemd creates /run/circle-scroll)."""
    try:
        tmp = STATUS_PATH + ".tmp"
        with open(tmp, "w") as f:
            f.write(text + "\n")
        os.replace(tmp, STATUS_PATH)
    except OSError:
        pass


def run_session(dev, cfg, settings, base_cfg, debug):
    """Circle-scroll the touchpad until the settings need a restart
    (switched off, or scroll style changed).  Speed and direction changes are
    applied on the fly."""
    log(f"Using {dev.path}: {dev.name}")
    time.sleep(0.5)       # let any key/finger already down settle before grabbing
    try:
        dev.grab()
    except OSError as err:
        dev.close()
        if err.errno != errno.EBUSY:
            raise
        log("The touchpad is busy: another program (probably another copy of circle-scroll,"
            " e.g. a test run in a terminal) is holding it. Retrying in 3 seconds...")
        write_status("busy")
        time.sleep(3)
        return
    pad = scroll = None
    frame, dropped = [], False
    try:
        geom = Geometry(dev)
        pad = make_virtual_pad(dev)
        scroll = WheelScroll(debug) if cfg["scroll_style"] == "wheel" else TouchpadScroll(debug)

        def pad_out(events):
            for etype, code, value in events:
                pad.write(etype, code, value)
            pad.syn()

        scroller = CircleScroller(cfg, geom, DeviceModel(dev), pad_out, scroll, debug)
        log(f"Circle: centre=({scroller.cx:.1f}, {scroller.cy:.1f}) mm, radius={scroller.r:.1f} mm,"
            f" scroll style: {cfg['scroll_style']}, {cfg['degrees_per_notch']:g} deg per notch")
        write_status("on")
        while True:
            ready, _, _ = select.select([dev.fd], [], [], 1.0)
            if ready:
                for ev in dev.read():
                    if ev.type == e.EV_SYN:
                        if ev.code == e.SYN_DROPPED:
                            dropped = True
                        elif ev.code == e.SYN_REPORT:
                            if not dropped:
                                scroller.handle_frame(frame)
                            frame, dropped = [], False
                        continue
                    frame.append((ev.type, ev.code, ev.value))
            if settings.changed():
                new = dict(base_cfg)
                new.update(settings.load())
                if (new["enabled"] != cfg["enabled"]
                        or new["scroll_style"] != cfg["scroll_style"]):
                    log("Settings changed; restarting")
                    return
                cfg.update(new)          # scroller reads cfg live
                log(f"Settings updated: {cfg['degrees_per_notch']:g} deg per notch,"
                    f" clockwise scrolls {'down' if cfg['clockwise_scrolls_down'] else 'up'}")
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        if scroll is not None:
            scroll.close()
        if pad is not None:
            pad.close()
        dev.close()


def run(base_cfg, user_config, debug):
    settings = UserSettings(user_config)
    try:
        while True:
            cfg = dict(base_cfg)
            cfg.update(settings.load())
            if not cfg["enabled"]:
                log("Circle scrolling is switched off; touchpad left alone.")
                write_status("off")
                while not settings.changed():
                    time.sleep(0.25)
                continue
            dev = find_touchpad(cfg["device_name"])
            if dev is None:
                log("No touchpad found (try --list and set device_name in the config).")
                write_status("no-touchpad")
                time.sleep(3)
                continue
            run_session(dev, cfg, settings, base_cfg, debug)
    except KeyboardInterrupt:
        pass


def fit_circle(points):
    """Least-squares circle fit (Kasa method). Returns (cx, cy, r)."""
    n = len(points)
    sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points); syy = sum(p[1] ** 2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    z = [p[0] ** 2 + p[1] ** 2 for p in points]
    sxz = sum(p[0] * zz for p, zz in zip(points, z))
    syz = sum(p[1] * zz for p, zz in zip(points, z))
    sz = sum(z)
    m = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]]
    rhs = [-sxz, -syz, -sz]

    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))

    d = det(m)
    sol = []
    for i in range(3):
        mi = [row[:] for row in m]
        for r in range(3):
            mi[r][i] = rhs[r]
        sol.append(det(mi) / d)
    D, E, F = sol
    cx, cy = -D / 2, -E / 2
    dists = sorted(math.hypot(p[0] - cx, p[1] - cy) for p in points)
    return cx, cy, dists[len(dists) // 2]


def calibrate(cfg, path, seconds):
    dev = find_touchpad(cfg["device_name"])
    if dev is None:
        log("No touchpad found.")
        sys.exit(1)
    geom = Geometry(dev)
    model = DeviceModel(dev)
    sx, sy = geom.size_mm()
    print(f"Touchpad: {dev.name}  ({sx:.1f} x {sy:.1f} mm sensor area)")
    print(f"Run ONE finger slowly around the very edge of the pad, several times,")
    print(f"for {seconds} seconds.  Starting now...", flush=True)
    points, frame = [], []
    end = time.time() + seconds
    dev.grab()   # stop the pointer jumping around while calibrating
    try:
        while time.time() < end:
            ev = dev.read_one()
            if ev is None:
                time.sleep(0.005)
                continue
            if ev.type == e.EV_SYN and ev.code == e.SYN_REPORT:
                model.apply(frame)
                frame = []
                if model.touching() and model.fingers() <= 1:
                    points.append(geom.mm(*model.position()))
            elif ev.type != e.EV_SYN:
                frame.append((ev.type, ev.code, ev.value))
    finally:
        dev.ungrab()
    if len(points) < 50:
        print(f"Only got {len(points)} samples; please try again.")
        sys.exit(1)
    cx, cy, r = fit_circle(points)
    print(f"Samples: {len(points)}")
    print(f"Circle centre: ({cx:.1f}, {cy:.1f}) mm   radius: {r:.1f} mm")
    cfg.update({"center_x_mm": round(cx, 2), "center_y_mm": round(cy, 2),
                "radius_mm": round(r, 2)})
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"Saved to {path}")


def main():
    ap = argparse.ArgumentParser(description="iPod-style circular scrolling for touchpads")
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--list", action="store_true", help="list input devices")
    ap.add_argument("--calibrate", action="store_true", help="measure the pad's circle")
    ap.add_argument("--seconds", type=int, default=15, help="calibration time")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--user-config", default="",
                    help="settings file written by the System Settings page (circlescrollrc)")
    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.list:
        for p in evdev.list_devices():
            d = evdev.InputDevice(p)
            kind = "ours    " if is_ours(d) else "touchpad" if is_touchpad(d) else "        "
            print(f"{d.path:20} {kind} {d.name}")
        return
    if os.geteuid() != 0:
        log("Note: reading the touchpad normally needs root (sudo).")
    if args.calibrate:
        calibrate(cfg, args.config, args.seconds)
    else:
        run(cfg, args.user_config, args.debug)


if __name__ == "__main__":
    main()
