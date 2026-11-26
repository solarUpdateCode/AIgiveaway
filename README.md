# AIgiveaway (Windows)

A lightweight, window-scoped local AI desktop assistant for Windows that watches a **single user-selected browser window** on [Cymatics.fm](https://cymatics.fm/) during livestream free drops and giveaways.

## Features

1. **Free Stuff Tracker & $0.00-Only Auto-Checkout**
   - Scans the tracked Cymatics page for unlocked free packs/plugins and adds them to cart.
   - Checks **Learn More** pages for free options and returns automatically if none are free.
   - Proceeds to checkout and completes the order **only when the total is explicitly `$0.00` / `FREE`** (hard safety stop on any paid total).
   - Automatically returns to the tracked livestream page after checkout to watch for newly unlocked drops.
2. **Fast Random Giveaway Question Solver**
   - Continuously watches for giveaway question popups/forms, answers quickly with Gemini Vision, fills your email (`karankrajbhar23@gmail.com` by default, editable in UI), and submits.
3. **One-Click ON / OFF Toggle + Background Tray Mode**
   - Turn the AI on or off anytime with a single button, and optionally hide the app to the Windows system tray while it runs in the background.
4. **Strict Single-Window Remote Scope (Not Whole Desktop)**
   - Uses Windows `PrintWindow` (`PW_RENDERFULLCONTENT`) to capture **only** the single window you select — never your whole desktop.
   - Sends clicks, scrolls, and typing strictly to that chosen window (`PostMessage` background mode by default so your cursor stays free, with an optional window-clamped focus fallback).
5. **Gemini API Key Support (`AQ.*` & `AIza*`)**
   - Supports both current Google AI Studio `AQ.*` Auth Keys (`generativelanguage.googleapis.com`) and Vertex AI Express keys with automatic endpoint fallback.
   - Your API key is stored **locally only** in `%APPDATA%\AIgiveaway\config.json` and is never committed to GitHub.

## Download & Install (Windows)

1. Go to the **Releases** page (or **Actions -> Build Windows App & Installer** artifacts) in this repository.
2. Download **`AIgiveaway-Setup-1.0.0.exe`** and run the installer.
3. Open your Cymatics livestream page in Chrome/Edge (keep the window open — it can sit behind other windows, just don't minimize it).
4. Launch **AIgiveaway**, select that browser window in **Allowed Window ONLY**, paste your Gemini API key, click **Test**, and click **TURN AI ON**.

## Build Locally on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
python -m app.icon_gen
pyinstaller --clean --noconfirm build/AIgiveaway.spec
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\AIgiveaway.iss
```

The installer will be created at `installer\output\AIgiveaway-Setup-1.0.0.exe`.
