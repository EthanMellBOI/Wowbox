# 🖨️ WOWBOX - Connecting Families with Love

WOWBOX is a heartwarming, fully-automated remote printing platform developed as part of **MiLab**. It is designed to bridge the distance between family members and their elderly loved ones by turning digital photos into physical memories in real-time.

Using a **Raspberry Pi** and a **Canon Ivy 2** printer, WOWBOX allows anyone in the family to send a "moment of happiness" directly into their loved one's home from anywhere in the world.

![WOWBOX Theme](https://img.shields.io/badge/Theme-Warm%20%26%20Emotional-red)
![Architecture](https://img.shields.io/badge/Architecture-Cloud%20to%20Hardware-orange)
![English UI](https://img.shields.io/badge/Language-English-blue)

---

## 🎨 Design Philosophy: "The Warm Connection"

Unlike traditional technical platforms, WOWBOX features a **Warm UI** inspired by the physical device:
*   **Soft Aesthetic:** Cream, wood-brown, and heart-red color palette.
*   **Emotional Feedback:** Floating background hearts and **"Heart Burst"** particle animations when a photo is successfully sent.
*   **Elderly Friendly:** Simple, large, and high-contrast interface designed for ease of use across generations.

---

## 🧙‍♂️ How It Works (The Simple Flow)

Think of WOWBOX as a **Smart Love Messenger**:

1.  **The Brain (Cloud Server):** We have a server in the cloud (hosted on Render). When a family member uploads a photo via the website, it sits in a secure "waiting room" (the Queue) ready to be collected.
2.  **The Messenger (Raspberry Pi Agent):** The Raspberry Pi inside the WOWBOX is the messenger. It constantly checks the cloud server, asking: *"Is there a new memory for me to deliver?"*
3.  **The Delivery (Printing):** As soon as it finds a photo, the Pi downloads it and speaks to the Canon Ivy printer via **Bluetooth**. The printer starts buzzing, the Heart on the box glows, and a physical photo slides out for the loved one to see.

---

## 🌟 Key Features

*   **Global Access:** Send photos from any smartphone, anywhere in the world.
*   **No Manual Interaction:** The system is "Plug & Play" for the receiver. No screens to touch, no menus to navigate.
*   **Self-Healing Agent:** The Pi agent is designed to automatically reconnect to the printer, wait for it if it's offline, and recover from power outages without any human intervention.
*   **Private & Secure:** Password-protected access ensures only family members can send photos.

---

## 🏗️ Architecture

The platform is split into two specialized units:

### 1. Cloud Server (`/server`)
A Python Flask application managing the web interface and the central print queue.
*   **Frontend:** Vanilla HTML/CSS/JS with a focus on CSS animations and mobile-first UX.
*   **Backend:** SQLite database for persistent queue management and API for agent communication.

### 2. Raspberry Pi Agent (`/agent`)
A robust Python daemon tracking the server.
*   **Systemd Service:** Runs as a persistent background service.
*   **Retry Logic:** If the printer is off, the agent waits and retries every 20 seconds, ensuring no photo is lost.
*   **Auto-Bluetooth:** Manages the Bluetooth socket stack (`rfcomm`) dynamically for each print to preserve battery and stability.

---

## 🚀 Quick Setup

### ☁️ Cloud (Server)
1. Deploy the `server/` directory (e.g., to Render).
2. Set `WOWBOX_PASSWORD` and `AGENT_KEY` environment variables.

### 🍓 Home (Raspberry Pi)
1. Flash the code to the SD card.
2. Connect the Pi to the internet (Ethernet is recommended for a seamless experience).
3. Update `config.py` with your Server URL and Printer MAC address.
4. Enable the service: `sudo systemctl enable wowbox-agent.service`.

---

*Built with ❤️ for MiLab: Connecting families, one photo at a time.*
