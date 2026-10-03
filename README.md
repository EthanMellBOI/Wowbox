# 🎁 Wowbox

Wowbox is an interactive, magical smart-box that bridges a cloud-based web application with physical hardware. Users can upload photos and voice messages via a web portal, and the physical Wowbox (powered by a Raspberry Pi) will notify the recipient with light animations and sound before physically printing the photo on a Canon Ivy 2.

## 🏗️ System Architecture

This repository is a **Monorepo** containing two distinct halves of the product:

### 1. The Web App (`WOWBOX_V2/`)
A Python Flask web application (designed to be hosted on Render). 
- Serves the frontend UI (`app.js`, `style.css`) for users to upload photos and record voice messages.
- Manages a print queue and provides an API for the physical Wowbox to securely poll for new jobs.

### 2. The Raspberry Pi Agent (`WOWBOX_FINAL/raspberry-pi/`)
A headless Python daemon running continuously on the Raspberry Pi inside the Wowbox.
- **`agent.py`:** The main brain. Securely polls the Web App API for new print jobs.
- **`hardware.py`:** Controls the physical arcade button and drives WS281x LED light animations. Handles PipeWire audio playback for ringtones and user voice messages.
- **Bluetooth Drivers (`ivy2.py`):** Establishes an RFCOMM Bluetooth connection to physically transmit and print the image to a Canon Ivy 2 pocket printer.
- **Speaker Keep-Alive:** Implements a continuous 19.5kHz inaudible payload (`silence.wav`) to prevent the internal JBL GO speaker from entering auto-sleep mode.

---

## 🚀 Raspberry Pi Setup Guide

### 1. Configuration
1. Navigate to the `raspberry-pi/agent/` directory.
2. Rename `config.py.example` to `config.py`.
3. Open `config.py` and enter your specific environment credentials:
   - `SERVER_URL`: The URL of your live Web App.
   - `AGENT_KEY`: The secret authentication key (must match the key on your web server).
   - `PRINTER_MAC`: The Bluetooth MAC address of your Canon Ivy 2.

### 2. Installation
Install the required system hardware libraries and python dependencies:
```bash
sudo apt-get install ffmpeg bluez bluetooth 
pip install -r requirements.txt


sudo cp wowbox-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wowbox-agent.service
sudo systemctl start wowbox-agent.service



Once you save that file, it will instantly render as a beautiful, formatted document on the front page of your repository. Your colleague is going to be incredibly impressed by how clean and professional your architecture is!
