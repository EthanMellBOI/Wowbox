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

## Main page overview – the box status at a glance

At the top of the main page (above the photo picker) a card shows, in plain language, whether the box is ready, receiving or printing a photo, or has a problem (printer off / out of paper / cover open, no connection, no sound), with small **Connection · Printer · Sound** dots. Tap it to open the full Status page.

## Status page – see what the box is doing without SSH

Open the web app, log in and tap the **box badge** in the header (or go to `/status`). It shows:

- **Overall health** in plain language, plus a **"what to check"** list with the fix for each problem.
- A **setup checklist**: box online · Wi-Fi/hotspot · internet · printer (battery, paper, cover) · speaker output.
- **What is happening right now**: photo received → waiting for button → printing.
- An **activity log** (filter: all / warnings / errors, with a Copy button) – logs are kept while the box is offline and delivered when it reconnects.
- **Quick actions**: test speaker, test lights, check printer now, restart box software.
- **Speaker volume**: big − / + buttons (10% steps, also un-mutes). Applied by the box within about 10 s.
- **Speaker confirmation**: after *Test speaker* the page asks "Did you hear the sound?". *No* turns the speaker red here and on the main page.
- Actions queued while the box is offline expire after 2 minutes, so nothing fires unexpectedly when it reconnects.

The Pi sends a heartbeat every 10 s; the box counts as *offline* after 30 s without one.

> Limits: the audio jack is output-only, so the Pi **cannot** detect a switched-off speaker or an unplugged cable – the "heard it?" confirmation after *Test speaker* is the real check (a USB microphone would be needed to automate it). The printer is checked about every 90 s (and on demand) – it must be switched on and in range.

## Handing the box to someone – setup steps

1. Plug in the box and the printer (switch the printer **on**, check paper and battery).
2. Turn on the phone **hotspot** the box was set up with (name/password must match).
3. Wait 1–2 minutes, open the web app → **Status**. Everything in the checklist should be green.
4. Press **Test speaker** (answer "Did you hear it?", adjust the volume with − / +) and **Test lights**, then send a test photo.

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

## Troubleshooting (no SSH needed)

| What you see | Likely cause / fix |
|---|---|
| "The WOWBOX is offline" | Box unplugged, or the phone hotspot / mobile data is off. Wait 1–2 min after power-up. |
| "The printer can't be reached" | Switch the Canon Ivy 2 on, charge it, keep it near the box, then *Check printer now*. |
| "Out of paper" / "cover open" | Load ZINK paper / close the cover. |
| "No sound" / speaker red | Turn the JBL on, check the cable at both ends, raise volume with + , then *Test speaker*. |
| Still stuck | *Restart box software*, then copy the activity log (Copy button) and send it to the developer. |

## Ideas for later

- **Faster delivery:** long-polling on `/api/agent/next` (pickup in under 1 s instead of up to 5 s) and resizing photos in the browser before upload (the Ivy 2 prints ~640×1616, so a 300 KB JPEG is enough; faster upload/download on a hotspot).
- **Warm printer link:** connect Bluetooth when a photo arrives (or keep it ready) to save 5–20 s.
- **Persistent storage on Render** (Postgres or a disk) so the queue, history and logs survive redeploys.
- **USB microphone** next to the speaker for an automatic end-to-end sound self-test.
- **Per-device agent keys** and key rotation; change the default web password.
- Refactor `agent.py` into a small state machine (idle → downloading → waiting → printing → error).

## Security notes

- Never commit real keys. `config.py`, `*.db` and `uploads/` are git-ignored.
- Change the default `WOWBOX_PASSWORD` and `SECRET_KEY` on Render.
- Agent logs mask the agent key and never print variable values in tracebacks.
