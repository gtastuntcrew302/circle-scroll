import importlib.util, math, time
spec = importlib.util.spec_from_file_location("cs", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "circle-scroll.py"))
cs = importlib.util.module_from_spec(spec); spec.loader.exec_module(cs)
from evdev import ecodes as e, AbsInfo

class FakeDev:
    phys = "i2c-SYNA0102:00"; name = "Synaptics TM3562-003"
    def capabilities(self, absinfo=True):
        ai = lambda mx, res: AbsInfo(0, 0, mx, 0, 0, res)
        c = {e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_TOUCH, e.BTN_TOOL_FINGER, e.BTN_TOOL_DOUBLETAP],
             e.EV_ABS: [(e.ABS_X, ai(1000, 25)), (e.ABS_Y, ai(1000, 25)), (e.ABS_MT_SLOT, ai(4, 0)),
                        (e.ABS_MT_TRACKING_ID, ai(65535, 0)), (e.ABS_MT_POSITION_X, ai(1000, 25)),
                        (e.ABS_MT_POSITION_Y, ai(1000, 25))]}
        if not absinfo: c[e.EV_ABS] = [k for k, _ in c[e.EV_ABS]]
        return c
    def absinfo(self, c): return AbsInfo(0, 0, 1000, 0, 0, 25)
    def input_props(self): return [e.INPUT_PROP_POINTER]

class FakeScroll:
    def __init__(self): self.total = 0.0; self.ends = 0
    def move(self, n): self.total += n
    def end(self): self.ends += 1

def mk():
    d = FakeDev(); pad = []; sc_out = FakeScroll()
    cfg = dict(cs.DEFAULTS, center_x_mm=20, center_y_mm=20, radius_mm=18)
    return cs.CircleScroller(cfg, cs.Geometry(d), cs.DeviceModel(d), lambda ev: pad.append(list(ev)), sc_out), pad, sc_out

def touch(sc, points, tid=1, lift=True):
    for i, (x, y) in enumerate(points):
        f = [(e.EV_ABS, e.ABS_MT_TRACKING_ID, tid), (e.EV_KEY, e.BTN_TOUCH, 1), (e.EV_KEY, e.BTN_TOOL_FINGER, 1)] if i == 0 else []
        sc.handle_frame(f + [(e.EV_ABS, e.ABS_MT_POSITION_X, x), (e.EV_ABS, e.ABS_MT_POSITION_Y, y), (e.EV_ABS, e.ABS_X, x), (e.EV_ABS, e.ABS_Y, y)])
    if lift:
        sc.handle_frame([(e.EV_ABS, e.ABS_MT_TRACKING_ID, -1), (e.EV_KEY, e.BTN_TOUCH, 0), (e.EV_KEY, e.BTN_TOOL_FINGER, 0)])

def circle(a0, a1, r=17, steps=60):
    return [(round((20 + r*math.cos(math.radians(a))) * 25), round((20 + r*math.sin(math.radians(a))) * 25))
            for a in [a0 + (a1 - a0) * i / steps for i in range(steps + 1)]]

def report(name, pad, so, sc):
    print(f"{name:44} pad_reports={len(pad):3} scroll_notches_down={so.total:+6.1f} ends={so.ends} final={sc.state}")

for name, pts in [("rim clockwise 1 turn (expect +18)", circle(0, 360)),
                  ("rim counter-clockwise 1/2 turn (expect -9)", circle(90, -90)),
                  ("centre swipe (expect forwarded, 0 scroll)", [(500 + 10*i, 500) for i in range(30)]),
                  ("rim tap (expect 2 reports: down, up)", [(925, 500), (926, 501)]),
                  ("rim then swipe inward (forwarded)", [(925 - 10*i, 500) for i in range(40)])]:
    sc, pad, so = mk(); touch(sc, pts); report(name, pad, so, sc)

# Inward from rim: the first report must be a single touch-down at the CURRENT spot (no burst = no jump)
sc, pad, so = mk(); touch(sc, [(925 - 10*i, 500) for i in range(40)])
first = dict(((t, c), v) for t, c, v in pad[0] if c in (e.ABS_X, e.BTN_TOUCH))
print("   inward: first report ABS_X =", first.get((e.EV_ABS, e.ABS_X)), "(finger had moved to ~", 925 - 10*3, "when decided)")

# Swallowed scroll, then a normal touch at the same spot it ended: the virtual pad must get the position
sc, pad, so = mk(); touch(sc, circle(0, 90)); pad.clear()
x, y = circle(0, 90)[-1]
sc.handle_frame([(e.EV_ABS, e.ABS_MT_TRACKING_ID, 2), (e.EV_KEY, e.BTN_TOUCH, 1), (e.EV_KEY, e.BTN_TOOL_FINGER, 1)])
sc.handle_frame([(e.EV_ABS, e.ABS_MT_TRACKING_ID, -1), (e.EV_KEY, e.BTN_TOUCH, 0), (e.EV_KEY, e.BTN_TOOL_FINGER, 0)])
flat = [ev for r in pad for ev in r]
print("   resync after scroll: ABS_X sent =", (e.EV_ABS, e.ABS_X, x) in flat, " MT_POSITION_X sent =", (e.EV_ABS, e.ABS_MT_POSITION_X, x) in flat)

# Real uinput: build the smooth-scroll touchpad and drive it
ts = cs.TouchpadScroll()
writes = []
orig = ts._write; ts._write = lambda evs: (writes.append(evs), orig(evs))
t0 = time.monotonic(); ts.move(1.0); ts.move(1.0); ts.end(); held = time.monotonic() - t0
ys = [v for w in writes for (t, c, v) in w if c == e.ABS_Y]
print(f"TouchpadScroll: name={ts.ui.name!r} reports={len(writes)} y_travel={(ys[-1]-ys[0])/ts.RES:.2f} mm for 2 notches"
      f" (expect {2*ts.MM_PER_NOTCH:.2f}); held {held:.2f}s before lift")
ts.close()
p = cs.make_virtual_pad(type("D", (FakeDev,), {"info": type("I", (), dict(vendor=0x06cb, product=0xcdea, version=0x100, bustype=0x18))})())
print("virtual pad name:", repr(p.name)); p.close()
