# Teetime Monitor for Linux — portable, nothing to install

*[Deutsche Version](LINUX-APP.de.md)*

A tarball you unpack and run in a terminal. No Python, no package manager, no root rights.

## Start it

1. Download **TeetimeMonitor-…-linux-x86_64.tar.gz** from the
   [latest release](https://github.com/ltdan-88/teetime-monitor/releases/latest).
2. Unpack it anywhere: `tar xzf TeetimeMonitor-*-linux-x86_64.tar.gz`
3. Open a terminal in the new `TeetimeMonitor` folder and run `./TeetimeMonitor.sh`.

**Browser version:** run `./TeetimeMonitor-Web.sh` for the app in a browser window instead (see
[WEBUI.md](WEBUI.md)); it has everything the terminal version has.

Add your first club and your pc caddie login from inside the app; the rest works like the terminal app
described in the [README](../README.md). A modern terminal (GNOME Terminal, Konsole, kitty, …) with
colours and UTF-8 looks best.

## Where your data lives

Everything — settings, logins, tee-time history — is in the folder **`userdata`** inside
`TeetimeMonitor`, and nowhere else. Deleting the folder removes every trace.

- **Update:** unpack the new version, then copy your old `userdata` folder into it.
- **Password:** your pc caddie password is saved as plain text in `userdata/config/.env`, created
  readable by your user only. Do not put the folder on a shared drive.

## Troubleshooting

- `./TeetimeMonitor.sh --doctor` checks the folders, the network, the certificates and the login and
  says what is wrong.
- Needs a 64-bit Intel/AMD Linux with **glibc 2.28 or newer** (Debian 10, Ubuntu 20.04, RHEL/Alma 8, or
  anything newer). **Not** for Alpine (musl) and **not** for ARM (Raspberry Pi) — use the Homebrew/pip
  install from the README there.
- There is no background scraper in the portable version: nothing runs while the app is closed.

## What is inside (for the curious)

`app/python` is python-build-standalone's relocatable CPython 3.12 plus the app's libraries;
`TeetimeMonitor.sh` sets `TEETIME_MONITOR_CONFIG_DIR` and `TEETIME_MONITOR_DATA_DIR` to `userdata/`
and starts it in isolated mode. The release job builds it, checks it in a clean environment
(`linux/verify_portable.py`) and runs it once inside AlmaLinux 8 (the glibc floor); see
[RELEASING.md](RELEASING.md).
