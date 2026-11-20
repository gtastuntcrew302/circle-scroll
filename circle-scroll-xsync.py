#!/usr/bin/env python3
"""circle-scroll-xsync: keeps circle-scroll's virtual touchpad using the same
settings (pointer speed, tapping, natural scrolling, enabled/disabled...) as
the real touchpad.

Why: on X11, KDE applies your touchpad settings once at login, to the real
touchpad only.  circle-scroll's virtual copy appears later and would otherwise
stay on default settings (e.g. pointer speed 0.0 instead of your 0.6).

Runs in your desktop session (autostarted), checks every 2 seconds, and only
changes something when a setting differs.  On Wayland it exits straight away,
because KDE's Wayland session already applies settings to the copy.
"""

import os
import re
import subprocess
import sys
import time

PAD_PHYS = "circle-scroll/pad"
INTERVAL_S = 2.0
# Settings that are information only, or can't usefully be copied.
SKIP_SUFFIXES = ("Default", "Available")
SKIP_PREFIXES = ("libinput Accel Custom",)
COPY_EXTRA = ("Device Enabled", "Coordinate Transformation Matrix")


def xinput(*args):
    r = subprocess.run(["xinput", *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def list_pointers():
    """[(id, name)] of all slave pointer devices."""
    _, out, _ = xinput("list", "--short")
    devs = []
    for line in out.splitlines():
        m = re.search(r"[↳~]\s+(.*?)\s+id=(\d+)\s+\[slave\s+pointer", line)
        if m:
            devs.append((m.group(2), m.group(1)))
    return devs


def list_props(dev_id):
    """{property name: value string}"""
    _, out, _ = xinput("list-props", dev_id)
    props = {}
    for line in out.splitlines():
        m = re.match(r"\s+(.+?) \(\d+\):\s*(.*)$", line)
        if m:
            props[m.group(1)] = m.group(2).strip()
    return props


def phys_of(props):
    node = props.get("Device Node", "").strip('"')
    if not node.startswith("/dev/input/event"):
        return ""
    try:
        with open(f"/sys/class/input/{os.path.basename(node)}/device/phys") as f:
            return f.read().strip()
    except OSError:
        return ""


def copyable(name, value):
    if value in ("", "<no items>") or value.startswith('"'):
        return False
    if name in COPY_EXTRA:
        return True
    return (name.startswith("libinput ") and not name.endswith(SKIP_SUFFIXES)
            and not name.startswith(SKIP_PREFIXES))


def main():
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or not os.environ.get("DISPLAY"):
        print("Not an X11 session; nothing to do.")
        return
    phys_cache = {}       # (id, name) -> phys
    failed = set()        # (clone id, prop, value) that xinput refused
    while True:
        try:
            devs = list_pointers()
            props_now = {}
            for dev_id, name in devs:
                key = (dev_id, name)
                if key not in phys_cache:
                    props_now[dev_id] = list_props(dev_id)
                    phys_cache[key] = phys_of(props_now[dev_id])
            present = set(devs)
            phys_cache = {k: v for k, v in phys_cache.items() if k in present}

            for (clone_id, name), phys in phys_cache.items():
                if phys != PAD_PHYS:
                    continue
                real = [i for (i, n), p in phys_cache.items()
                        if n == name and not p.startswith("circle-scroll")]
                if not real:
                    continue
                want = props_now.get(real[0]) or list_props(real[0])
                have = props_now.get(clone_id) or list_props(clone_id)
                for prop, value in want.items():
                    if not copyable(prop, value) or have.get(prop) == value:
                        continue
                    if (clone_id, prop, value) in failed:
                        continue
                    rc, _, err = xinput("set-prop", clone_id, prop,
                                        *[v.strip() for v in value.split(",")])
                    if rc == 0:
                        print(f"[{clone_id}] {prop} = {value}", flush=True)
                    else:
                        failed.add((clone_id, prop, value))
                        print(f"[{clone_id}] could not set {prop}: {err.strip()}", flush=True)
        except FileNotFoundError:
            print("xinput is not installed (sudo apt install xinput).", file=sys.stderr)
            sys.exit(1)
        except Exception as err:          # keep going; the next pass retries
            print(f"error: {err}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
