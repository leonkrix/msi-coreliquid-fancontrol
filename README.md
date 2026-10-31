# msi-coreliquid-fancontrol

Quiet, temperature-driven fan and pump curves for the **MSI MPG CoreLiquid K360** on Linux, as a small systemd service. It uses [liquidctl](https://github.com/liquidctl/liquidctl) as a library for the USB communication.

Under Windows, MSI Center feeds the cooler the CPU temperature and the cooler follows its fan curves. Without that software the K360 sits at a fixed default (here: radiator fans 60 %, pump 100 %, which is loud). The cooler has no temperature sensor of its own, so a one-off `liquidctl set ... speed` is not enough: something has to keep telling it the CPU temperature. This service does that.

What it does:

- programs one curve per channel (radiator fans, water block fan, pump), gentle at low temperature and steeper towards the top
- reads the CPU temperature (`k10temp`, Tctl), low-pass filters it so short load bursts do not make the fans jump, and sends it to the cooler once a second
- puts CPU temperature, CPU clock and radiator fan speed on the cooler's display
- re-applies everything after power loss, suspend or a USB reset (the cooler forgets its settings then)
- writes its state to `/run/msi-aio-fancontrol/status.json`

Tested on: MSI MPG X570 GAMING PLUS, Ryzen 7 5800X, Debian 13 (trixie), kernel 6.12, liquidctl 1.15.0 (Debian package `1.15.0-2`), K360 at USB ID `0db0:b130`. The K360 is listed as *experimental* in [liquidctl's guide](https://github.com/liquidctl/liquidctl/blob/main/docs/msi-mpg-coreliquid-guide.md). Other MPG CoreLiquid models are untested, and the script only matches `0db0:b130`.

## Curves

CPU temperature (Tctl) to duty, interpolated linearly by the cooler:

| Tctl | radiator fans | water block fan | pump |
|---|---|---|---|
| up to 40 °C | 25 % | 30 % | 60 % |
| 58 °C | 33 % | 36 % | 66 % |
| 78 °C | 55 % | 55 % | 82 % |
| 90 °C | 100 % | 100 % | 100 % |

For example, the radiator fans run at 46 % at 70 °C, 52 % at 75 °C, 62 % at 80 °C and 81 % at 85 °C. At idle (Tctl 40-50 °C) that is about 650-800 rpm on the radiator fans and about 2000 rpm on the pump. The values are constants at the top of [`msi-aio-fancontrol`](msi-aio-fancontrol); edit them and restart the service.

The curve is deliberately gentle below 80 °C: the CPU is specified for 90 °C and limits its own clock there, so the fans only reach full speed at 90 °C. If you prefer more margin under long full load, move the last point to a lower temperature, for example 85 or 88 °C.

### Things learned about the K360

- The cooler keeps **4 points per channel** on this unit, not the 7 that the driver and liquidctl's protocol notes describe. A raw write of 7 points reads back as 4 points plus zeros, and the fans stayed at the 4th point's duty at temperatures above it. So this comes from the device, not from the driver; I have only tried one unit (reported as liquidctl/liquidctl#939).
- **Above the last point the cooler holds that point's duty.** A curve that does not end at 100 % would stop cooling harder at high temperature. The script refuses to start with such a curve.
- Hardware limits: radiator fans 20-100 %, pump 60-100 %, water block fan 0-100 %.
- The cooler slews on its own, about +4 %/s up and about -1.5 %/s down, and it keeps using the last temperature it was sent.
- **liquidctl 1.15 stores the profile with temperature and duty swapped.** The CLI, the guide and `yoda` use (temperature, duty) pairs, but `MpgCooler.set_speed_profile` and `set_profiles` unpack (duty, temperature). Checked on this cooler: `liquidctl set fans speed 30 25 50 40 70 70 90 100` (30 °C to 25 %, ..., 90 °C to 100 %) stores the duties 30, 50, 70, 90 and the temperatures 25, 40, 70, 100, and the fans only reach 90 % at 100 °C. The same two lines are still in liquidctl 1.16.0 and in `main`. With the order fixed in a patched copy, the same command stores what it says. Reported as liquidctl/liquidctl#937, with a fix in liquidctl/liquidctl#938. The example in the guide, with 5 pairs, would also lose its 5th pair on this cooler.
- That is why the script writes the configuration with the low-level `set_fan_config` / `set_fan_temp_config` and reads it back to verify it. It depends on private names (`_FanConfig`, `_FanMode`, `_FanTempConfig`) of liquidctl, so pin the version you tested. If liquidctl fixes the order, the script keeps working, because it does not use `set_speed_profile`.

### Load bursts

The filter has a 10 s time constant when the temperature rises and 3 s when it falls. Measured with all 16 threads loaded for a fixed time, starting from idle:

| load | radiator fans (idle value, peak) | Tctl peak |
|---|---|---|
| 2 s | 29 % to 38 % | 82 °C |
| 8 s | 30 % to 50 % | 90 °C |

These numbers are with the current curves. With the earlier, steeper curves (100 % at 85 °C) the same bursts took the fans to 35 % and 56 %, and with an even faster filter (5 s up, 6 s down) to 42 % and 71 %.

After a burst, the fans need around 20-35 s to settle again (about 23 s after the 8 s burst). The cooler's own slew and the time the CPU needs to cool down set that, not the filter. [`tools/burst_test.py`](tools/burst_test.py) reproduces the measurement. It reads only the status file and the CPU sensor.

## Install

```bash
sudo apt install liquidctl
sudo install -m 755 msi-aio-fancontrol /usr/local/sbin/msi-aio-fancontrol
sudo install -m 644 msi-aio-fancontrol.service /etc/systemd/system/msi-aio-fancontrol.service
sudo systemctl daemon-reload
sudo systemctl enable --now msi-aio-fancontrol
```

The service runs as root so that it starts at boot, before anyone logs in. Check it:

```bash
systemctl status msi-aio-fancontrol
cat /run/msi-aio-fancontrol/status.json
journalctl -u msi-aio-fancontrol
```

Try the script by hand without touching the cooler: `python3 -I msi-aio-fancontrol --dry-run -v`. `--show-curves` prints the curves.

## Notes and limits

- **Do not run `liquidctl` against the cooler while the service is running.** Replies from the device get mixed up and either side can time out. Stop the service first (`sudo systemctl stop msi-aio-fancontrol`) or read the status file.
- **When the service stops**, it sends 80 °C and the cooler stays at that operating point (fans about 62 %, pump about 85 %, roughly what the cooler did by default before), so it cannot be left cool by mistake. If the process is killed with `SIGKILL` the cooler keeps whatever it was last told.
- **If the CPU temperature cannot be read**, the service reports 90 °C and the cooler ramps up.
- The cooler loses its settings when it loses power. The service checks every 30 s that the curves are still stored and re-applies them if not.
- The display can be changed with `DISPLAY` in the script. Valid items: `cpu_temp`, `cpu_freq`, `gpu_freq`, `gpu_usage`, `fan_pump`, `fan_radiator`, `fan_cpumos`. This service only feeds CPU values. The temperature on the display is the filtered one.
- Case fans on the mainboard headers are not handled here. They follow the BIOS fan curves, or can be controlled through the `nct6775` hwmon driver (`modprobe nct6775`).

Undo everything:

```bash
sudo systemctl disable --now msi-aio-fancontrol
sudo rm /etc/systemd/system/msi-aio-fancontrol.service /usr/local/sbin/msi-aio-fancontrol
sudo systemctl daemon-reload
```

The cooler keeps its curve until it next loses power.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). The script uses liquidctl as a library, and liquidctl is GPL-3.0-or-later too. This project is not affiliated with MSI or with liquidctl. Use it at your own risk and watch your temperatures: it controls the pump and fans of a liquid cooler.
