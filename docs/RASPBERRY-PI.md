# Teetime Monitor on a Raspberry Pi (a home web server)

*[Deutsche Version](RASPBERRY-PI.de.md)*

A Raspberry Pi that is always on can run Teetime Monitor for the whole household: it fetches the tee sheets
on its own, and every phone, tablet and computer on your home network opens
the same browser version (see the [README](../README.md)), behind a password. Nothing runs on those devices.

**What you need:** a Raspberry Pi 3, 4, 5 or Zero 2 W with **64-bit** Raspberry Pi OS "Bookworm" (12) or
newer (Python 3.11+), on your network, and the Pi's time zone set to the club's (`sudo raspi-config` >
Localisation). About 400 MB of disk. Any other always-on Debian/Ubuntu machine works the same way.

## Install

On the Pi (over SSH or a terminal), as your normal user:

```bash
curl -fsSL https://raw.githubusercontent.com/ltdan-88/teetime-monitor/main/deploy/raspberry-pi/install.sh | bash
```

It installs the newest release into its own Python environment (`~/.local/share/teetime-monitor-server`),
asks you for a **password**, and sets up a service that starts at boot and restarts after a crash. It
finishes by printing the addresses, such as `http://raspberrypi.local:8765`. Options: `--port 9000`,
`--version v0.78.0`, `--no-service` (start it yourself), `--no-password`. Run it again to update.

Then, from any device on your network: open the address, log in with the password, and set up as on any
computer: **Settings > pc caddie login** and add your clubs (**Add club**). The first
fetch happens within minutes; **Refresh** does it at once. Your settings live in `~/.config/teetime-monitor`
and the data in `~/.local/share/teetime-monitor` on the Pi.

## How it works

- `teetime-monitor-web --serve` listens on the network (port 8765 by default) and keeps running. Every few
  minutes it checks each saved club and fetches what its own scrape intervals say is due (Settings >
  Scraping), notes booking changes, and takes the day's backup (the newest 7 are kept).
- A phone or tablet just opens the address; add it to the home screen for an app-like icon. The layout
  adapts to phones and tablets.
- The password is set with `teetime-monitor-web --set-password` and changed later in **Settings > Server password**. It is stored only as a salted hash in
  `~/.config/teetime-monitor/web_auth.json` (readable by you only). Logging in gives a browser a cookie for 30
  days (**View > Log out** ends it); changing the password logs every browser out. Five wrong guesses lock
  that device out for 30 seconds, doubling each time.

## Updates

Every few hours (and when a page asks while the last look is over an hour old) the server looks at GitHub's public release list (one plain request, nothing about you is sent)
and, when a newer version exists, every page shows **Version X is available** in the footer, with a link to the
release notes. On the Pi, **Update now** (in the same footer line) installs that release into the server's own
environment and restarts the service; the page reconnects by itself. It only ever installs the release the
server found itself, from this project's GitHub page. If an update fails, the old version keeps running and the
page says why. To switch the look off, add `Environment=TEETIME_MONITOR_NO_UPDATE_CHECK=1` to the service
(`sudo systemctl edit teetime-monitor`). A server installed with 0.78.0 gets the button after one more run of
the install command.

## Security: read this

- It is **plain HTTP on your home network**. Everyone on your Wi-Fi can reach the login page, and someone who
  can watch the Wi-Fi traffic could read the password. Use a password you use nowhere else, and keep guests
  on a separate guest network.
- Behind the password sits your pc caddie login (the server needs it to fetch for you). Do
  not forward a port on your router to it.
- To reach it **away from home**, use a VPN into your home network: [Tailscale](https://tailscale.com) is the
  easy route (install it on the Pi and on your phone; no router settings), or WireGuard.

## Everyday

| | |
|---|---|
| Is it running? | `systemctl status teetime-monitor` |
| Look at its log | `journalctl -u teetime-monitor -n 50` (add `-f` to follow) |
| Restart / stop | `sudo systemctl restart teetime-monitor` / `sudo systemctl stop teetime-monitor` |
| Change the password | in the page: **Settings > Server password** (current password, new one twice; this browser stays logged in, every other device has to log in again). Or on the Pi: `~/.local/share/teetime-monitor-server/venv/bin/teetime-monitor-web --set-password` (also if you forgot it) |
| Update | the page shows "Version X is available · Update now" in its footer; one click installs it and restarts the server (about a minute or two). Or run the install command again |
| Remove it | `sudo systemctl disable --now teetime-monitor; sudo rm /etc/systemd/system/teetime-monitor.service; rm -rf ~/.local/share/teetime-monitor-server` (your settings and data stay in `~/.config` and `~/.local/share`) |

**Back up** `~/.config/teetime-monitor` (settings, your logins) and `~/.local/share/teetime-monitor` (history);
copying those two folders is a full backup. An SD card is the weak spot of any Pi: a good card (or an SSD)
and a copy of those folders now and then are worth it.

## If something does not work

- **The address does not open.** Try the numeric address the installer printed (`http://192.168.x.x:8765`);
  `raspberrypi.local` needs mDNS (built into macOS, iOS and recent Windows/Android; on some networks it does
  not work). Check the service: `systemctl status teetime-monitor`.
- **"Address already in use".** Another program has the port: install with `--port 9000`.
- **Times look wrong.** Set the Pi's time zone (see above).
- **"Login rejected" or no player names.** That is the pc caddie login: Settings > pc caddie login on any
  device.
- **A newer Python is needed** (older Raspberry Pi OS): update the OS to Bookworm or newer.
