#!/usr/bin/env python3
"""Measure how the cooler reacts to short CPU load bursts.

Only reads the service's status file and the CPU sensor, so it never talks to
the cooler itself.
"""
import glob, json, multiprocessing as mp, sys, time

STATUS = "/run/msi-aio-fancontrol/status.json"
BURSTS = [float(x) for x in sys.argv[1:]] or [2.0, 8.0]
IDLE_FANS = 28  # settled when the radiator fans are at or below this duty
OBSERVE = 40  # seconds observed after each burst


def load(seconds):
    end = time.time() + seconds
    while time.time() < end:
        pass


def tctl_path():
    for n in glob.glob("/sys/class/hwmon/hwmon*/name"):
        if open(n).read().strip() == "k10temp":
            return n.replace("name", "temp1_input")


tp = tctl_path()
tctl = lambda: int(open(tp).read()) / 1000
status = lambda: json.load(open(STATUS))

for burst in BURSTS:
    t0 = time.time()
    while status()["radiator_fan_duty"] > IDLE_FANS and time.time() - t0 < 180:
        time.sleep(2)
    s = status()
    print(f"\n=== {burst:g} s Volllast (Start: Lüfter {s['radiator_fan_duty']}%, Tctl {tctl():.0f}) ===", flush=True)
    procs = [mp.Process(target=load, args=(burst,)) for _ in range(16)]
    start = time.time()
    [p.start() for p in procs]
    peak_fan = peak_t = 0
    back = None
    n = 0
    while time.time() - start < burst + OBSERVE:
        t = time.time() - start
        s = status()
        fan, tc = s["radiator_fan_duty"], tctl()
        peak_fan, peak_t = max(peak_fan, fan), max(peak_t, tc)
        if t > burst and back is None and fan <= IDLE_FANS:
            back = t - burst
        if n % 2 == 0:
            print(f"  t={t:5.1f}s  Tctl {tc:4.0f}  gefiltert {s['control_temp']:5.1f}  Lüfter {fan:3d}%  "
                  f"Pumpe {s['pump_duty']:3d}%", flush=True)
        n += 1
        time.sleep(1)
    [p.join() for p in procs]
    back_txt = "nicht innerhalb der Beobachtung" if back is None else f"{back:.0f} s"
    print(f"  -> Tctl-Spitze {peak_t:.0f} C, Lüfter-Spitze {peak_fan}%, zurück auf Leerlauf nach {back_txt} (ab Lastende)",
          flush=True)
