# MeeTunnel v1.0

MeeTunnel is a high-performance data-over-video tunneling solution that allows you to transmit UDP data through video conferencing platforms (like Google Meet, Zoom, or Teams) using dynamically generated QR codes.

## Features

- **UDP Tunneling:** Encapsulates standard UDP packets into a series of QR code fragments.
- **Virtual Camera Integration:** Uses `pyvirtualcam` to inject data directly into video calls.
- **Dual Capture Modes:** 
  - **Screen Capture:** High-speed desktop area monitoring using `mss`.
  - **Chrome Extension:** Direct video element capture to bypass window occlusion issues.
- **Reliable Reassembly:** Custom protocol header with magic bytes, packet IDs, and fragmentation support.
- **Built-in UI:** Easy-to-use Tkinter interface for configuration and monitoring.

## Prerequisites

1. **Virtual Camera Driver:** You must install UnityCapture. This provides the "Unity Video Capture" device that the sender uses to output QR codes.
2. **Python 3.8+**
3. **Chrome Browser:** If you intend to use the browser extension capture method.

## Installation

Install the required Python dependencies:

```bash
pip install qrcode[pil] pyvirtualcam opencv-python mss numpy
```

## Component Overview

### 1. Python Application (`main.py`)
The core application handles both the Sender and Receiver logic.
- **Sender:** Listens on a local UDP port (default 9000), fragments incoming data, generates QR codes (Version 10, High Error Correction), and sends them to the virtual camera.
- **Receiver:** Scans a defined screen area or receives frames from the Chrome extension, decodes the QR codes, reassembles fragments based on Packet IDs, and forwards the original data to a target local UDP port (default 9001).

### 2. Chrome Extension
Located in `chrome extension/`. This captures the video stream directly from the browser DOM.
- **To Install:** 
  1. Open Chrome and go to `chrome://extensions/`.
  2. Enable "Developer mode".
  3. Click "Load unpacked" and select the `chrome extension` folder.

## Usage Instructions

### Step 1: Start the Sender
1. Run `python main.py`.
2. In the **Sender** tab, click **Start Sender**.
3. Open Google Meet and set your camera to **Unity Video Capture**.
4. Send data to `127.0.0.1:9000` (e.g., using a tool like Packet Sender).

### Step 2: Start the Receiver
1. Run another instance of `main.py` (or use the same one if testing locally).
2. In the **Receiver** tab:
   - **Method A (Screen):** Use **Select Area with Mouse** to highlight the incoming video feed.
   - **Method B (Extension):** Check **Enable Chrome Extension Capture** and ensure the extension is active in your Meet tab.
3. Click **Start Receiver**.
4. Your reassembled data will be output to `127.0.0.1:9001`.

## Protocol Specification

MeeTunnel uses a custom 12-byte header for every QR fragment:

| Offset | Size | Name | Description |
| :--- | :--- | :--- | :--- |
| 0 | 2 | Magic | Fixed bytes `QN` |
| 2 | 1 | Version | Protocol version (current: 1) |
| 3 | 1 | Type | 1 = Handshake, 2 = Data |
| 4 | 4 | PktID | Incremental Sequence Number |
| 8 | 1 | FragIdx | Current fragment index |
| 9 | 1 | FragTotal | Total fragments for this packet |
| 10 | 2 | Length | Payload length |

## Troubleshooting

- **No Video Output:** Ensure no other application is using the UnityCapture driver.
- **Low Throughput:** If the video quality is poor, OpenCV may struggle to decode. Try increasing the lighting or reducing the `chunk_size` in `main.py`.
- **CORS Errors:** The Chrome extension requires the Python server to be running on port 5001 to accept POST requests.