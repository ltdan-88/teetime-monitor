# Teetime Monitor for Windows — portable, nothing to install

*[Deutsche Version](WINDOWS-APP.de.md)*

A zip file you unpack and run. No Python, no Scoop, no administrator rights, no installer. It
also runs from a USB stick or a folder on a locked-down work PC.

## Start it

1. Download **TeetimeMonitor-…-windows-x64.zip** from the
   [latest release](https://github.com/ltdan-88/teetime-monitor/releases/latest).
2. If Windows marks the download as coming from the internet, right-click the zip → **Properties** →
   tick **Unblock** → OK. Do this *before* unpacking (otherwise every file inherits the mark and
   Windows asks again and again).
3. Right-click the zip → **Extract All…** and pick any folder (Desktop, Documents, a USB stick).
4. Open the folder **TeetimeMonitor** and double-click **TeetimeMonitor.cmd**.
5. If Windows says *“Windows protected your PC”*, click **More info → Run anyway**. The app is not
   signed with a paid certificate, so Windows does not know it yet.

A black window opens and the app starts in it. It looks nicer in **Windows Terminal** (open it, drag
`TeetimeMonitor.cmd` into it, press Enter). Add your first club and your pc caddie login from inside
the app (the on-screen keys are listed at the bottom); the rest works like the terminal app described
in the [README](../README.md).

## Where your data lives

Everything — settings, logins, tee-time history — is in the folder **`userdata`** next to
`TeetimeMonitor.cmd`, and nowhere else on the PC. Deleting the folder removes every trace.

- **Update:** download and unpack the new version, then copy your old `userdata` folder into it.
- **Password:** your pc caddie password is saved as plain text in `userdata\config\.env`. Keep the
  folder on a drive only you can read.

## Troubleshooting

- Open a Command Prompt in the folder and run `TeetimeMonitor.cmd --doctor`: it checks the folders,
  the network, the certificates (it uses the Windows certificate store, so a company proxy is fine)
  and the login, and says what is wrong.
- **The window closes, or nothing happens:** a company security product may block programs that run
  from user folders (AppLocker, antivirus). The IT department can allow the folder, or use the
  app on a private PC. The runtime is python.org's own signed Python, not a custom `.exe`, which
  helps with allow-lists but cannot get around a policy that blocks everything.
- **Strange boxes instead of lines:** use Windows Terminal rather than the old console window.
- Windows 10 or 11, 64-bit (also on ARM PCs, which emulate it). The portable version has no
  background scraper: nothing runs while the window is closed.

## What is inside (for the curious)

`app\` holds python.org's embeddable CPython 3.12 and the app's libraries; `TeetimeMonitor.cmd`
sets `TEETIME_MONITOR_CONFIG_DIR` and `TEETIME_MONITOR_DATA_DIR` to `userdata\` and starts
`app\python.exe`. The release job builds it and checks it on a clean Windows runner
(`windows/verify_portable.py`); how to build it yourself is in [RELEASING.md](RELEASING.md).
