# 🎁 Wowbox

Wowbox is an interactive smart-box that bridges a cloud web app with physical hardware. Family members upload a photo (and an optional voice message) in the web app. The Raspberry Pi inside the box lights up and plays a sound, and when the recipient presses the button it prints the photo on a Canon Ivy 2 and plays the voice message.

## Architecture

```
 Phone / browser ──► Web app (Flask on Render)  ◄── polls + heartbeat ──  Raspberry Pi agent ──► Canon Ivy 2 (Bluetooth)
   upload photo        print queue, /status                               LEDs, button, speaker
```

| Part | Folder | What it does |
|---|---|---|
| Web app | `WOWBOX_V2/` | Flask app: login, upload, print queue, **Status page** (`/status`), agent API |
| Pi agent | `WOWBOX_FINAL/raspberry-pi/agent/` | Polls for jobs, drives LEDs/button/audio, prints, reports health |
| Printer driver | `WOWBOX_FINAL/raspberry-pi/*.py` | Canon Ivy 2 Bluetooth (RFCOMM) protocol |

Key agent files: `agent.py` (brain), `hardware.py` (LEDs, button, audio), `diagnostics.py` (health + log shipping).

## Status page – see what the box is doing without SSH

Open the web app, log in and tap the **box badge** in the header (or go to `/status`). It shows:

- **Overall health** in plain language, plus a **"what to check"** list with the fix for each problem.
- A **setup checklist**: box online · Wi-Fi/hotspot · internet · printer (battery, paper, cover) · speaker output.
- **What is happening right now**: photo received → waiting for button → printing.
- An **activity log** (filter: all / warnings / errors, with a Copy button) – logs are kept while the box is offline and delivered when it reconnects.
- **Quick actions**: test speaker, test lights, check printer now, restart box software.

The Pi sends a heartbeat every 10 s; the box counts as *offline* after 30 s without one.

> Limits: the Pi cannot detect whether the audio cable is physically plugged in – use **Test speaker** and listen. The printer is checked about every 90 s (and on demand) – it must be switched on and in range.

## Handing the box to someone – setup steps

1. Plug in the box and the printer (switch the printer **on**, check paper and battery).
2. Turn on the phone **hotspot** the box was set up with (name/password must match).
3. Wait 1–2 minutes, open the web app → **Status**. Everything in the checklist should be green.
4. Press **Test speaker** and **Test lights**, then send a test photo.

Button tips: **hold 5 s** = restart box software · **triple-click** = toggle demo mode (green flash = ON, no printing; blue flash = OFF).

## Raspberry Pi setup

On the Pi the code lives in `/home/wowbox_milab/ivy2/platform/` (the `agent/` folder from this repo plus the printer driver files next to it).

1. Copy `agent/config.py.example` to `agent/config.py` (it reads `WOWBOX_SERVER`, `AGENT_KEY`, `PRINTER_MAC` from the environment).
2. Install: `sudo apt-get install ffmpeg bluez` and `pip install -r requirements.txt`.
3. Edit `agent/wowbox-agent.service`: put the real `AGENT_KEY` **on the Pi only**, then:

```bash
sudo cp wowbox-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wowbox-agent.service
```

Useful commands: `sudo journalctl -u wowbox-agent.service -f` (live log) · `sudo systemctl restart wowbox-agent.service`.

## Web app (Render)

Deploy `WOWBOX_V2/` (see `Procfile`). Environment variables: `SECRET_KEY`, `WOWBOX_PASSWORD`, `AGENT_KEY` (must equal the Pi's key). Set `FLASK_DEBUG=1` only for local development.

> The SQLite database and uploads live on Render's local disk and are **not persistent** on the free tier – the print queue, status and activity log reset when the service redeploys or restarts.

## Security notes

- Never commit real keys. `config.py`, `*.db` and `uploads/` are git-ignored.
- Change the default `WOWBOX_PASSWORD` and `SECRET_KEY` on Render.
- Agent logs mask the agent key and never print variable values in tracebacks.
