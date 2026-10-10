# The teetime-monitor Mac app — download and use

*[Deutsche Version](MAC-APP.de.md)*

A normal Mac app for looking at your golf club's tee sheet: one card per bookable day with
the weather, how busy it is, and the time worth taking. Nothing else to install — no
Homebrew, no Python, no Terminal. Everything it needs is inside the app.

**What you need:** a Mac with an Apple chip (M1 or newer) and macOS 14 (Sonoma) or newer.

**How to check in three clicks:** click the Apple menu  in the top-left corner, click
**About This Mac**, and look at two lines: **Chip** should say *Apple M1* (or M2, M3, M4 …),
and the macOS version should be **14** or higher. If it says *Intel*, this download is not for
that Mac.

(Friends on Windows or Linux: the terminal version of teetime-monitor works for you — see the
[README](../README.md).)

## 1. Download

Open the [latest release](https://github.com/ltdan-88/teetime-monitor/releases/latest) and
download the file named **TeetimeMonitor-…-arm64.zip** (under *Assets*). It is about 60 MB.

## 2. Unzip and move it to Applications

1. Double-click the zip in your Downloads folder. A file called **TeetimeMonitor** (the app)
   appears next to it.
2. Drag **TeetimeMonitor** into your **Applications** folder.

## 3. The first time you open it

macOS will warn that it cannot verify the app. **That is expected, and it
does not mean something is wrong.** macOS only trusts apps that come from the App Store or
whose maker pays Apple for an extra check (called notarization). This app is a free hobby
project, so it has neither. The whole source code is public at
[github.com/ltdan-88/teetime-monitor](https://github.com/ltdan-88/teetime-monitor), and the
app only ever reads your club's tee sheet — it never books anything.

You tell your Mac once that you trust it:

**On macOS 15 (Sequoia) or newer**

1. Open the app by double-clicking it. A message appears; click **Done** (do not click *Move
   to Trash*).
2. Open the Apple menu  → **System Settings** → **Privacy & Security**.
3. Scroll down to the **Security** section. It says *“TeetimeMonitor” was blocked…*. Click
   **Open Anyway**, then enter your Mac password (or use Touch ID) and click **Open Anyway**
   once more.

**On macOS 14 (Sonoma)**

1. In the Applications folder, hold the **Control** key and click the app (or right-click it),
   then choose **Open**.
2. A message appears, this time with an **Open** button. Click it.

After that the app opens normally with a double-click, every time. If it still does not open,
use the Privacy & Security method above — it works on every version.

**If the app opens but never shows any data.** macOS can also put its “downloaded from the
internet” mark on the parts inside the app. If you pressed **Refresh** and nothing ever loads,
open **Terminal** (Spotlight: ⌘Space, type *Terminal*), paste the line below, press Return, and
open the app again:

```
xattr -dr com.apple.quarantine /Applications/TeetimeMonitor.app
```

(If you did not move the app to Applications, use its real location instead.)

## 4. Add your club

Open the **Actions** menu in the menu bar at the top of the screen and choose **Add Club…**
(⌘N), or open **Settings** (the gear icon in the toolbar) and use the **Clubs** section. Find
your club by name and press **Add**. (The **Open** button next to a club only previews its tee
sheet, without saving the club.)

Adding a club only saves it; it does not fetch any tee times yet. Press **Refresh** (⌘R) once to
load the first tee times — that takes a few seconds.

## 5. Optional: log in to pc caddie

Without a login the app already shows tee times, weather and how busy it is. If you log in
(**Settings → pc caddie login**), it can also show your own confirmed bookings and — if your
club shares them — player names, and it can prefer times with your friends.

Your username and password are saved in a file on your own Mac and used only to talk to pc
caddie. They are not sent anywhere else, and not to anyone who made this app. (They are kept
in a plain file in the folder named below, not in the macOS Keychain.)

## What you see, and what it does not do

Each bookable day is a card with its weather, how full the tee sheet is and the recommended
time (★); click a day to see every tee time. The app **only reads** the club's public tee
sheet (and your bookings, if you logged in) — it **never books** or changes anything.

It does not refresh by itself in the background. Press **Refresh** (⌘R) when you want the
latest tee times; the day list updates the moment the new data arrives, and the small dot at the
bottom of the window (next to when it was last updated) turns orange when the data is getting old.

## Where your data lives, and how to remove everything

The app keeps its saved clubs and settings in two folders in your home folder. They are
hidden, so to open one: in Finder choose **Go → Go to Folder…** (⇧⌘G) and paste:

- `~/.config/teetime-monitor` — your clubs, preferences, login
- `~/.local/share/teetime-monitor` — the tee-sheet history the app collected

To remove it all: quit the app, drag **TeetimeMonitor** from Applications to the Trash, and
drag those two folders to the Trash as well. (macOS may keep a few bytes of window settings
elsewhere; they do no harm.)

## Something went wrong?

Send a screenshot of the window, and the **app version** — the small grey number at the bottom
of the window, for example *v0.71.2* — and your macOS version (Apple menu → About This Mac).
That is usually enough to find the problem. Please never send your password.

If the app ever says a helper was *“not found — install it with Homebrew”*, ignore the Homebrew
part: it means your copy of the app is damaged. Delete it and download it again (step 1).
