# Drone Detection — RUBIK Pi 3

**Roni Bandini · May 2026 · Argentina · [@RoniBandini](https://twitter.com/RoniBandini)**

Audio-based drone detection running on a Qualcomm RUBIK Pi 3. An Edge Impulse audio classifier listens continuously for drone sounds; when confidence exceeds a configurable threshold, a webcam snapshot is taken and analyzed by a local instance of OpenClaw to confirm the presence of a drone, identify its make and model, and decide whether to log or alert. Alerts are delivered via Telegram and a physical LED on the GPIO.

---

## How It Works

```
Microphone
    │
    ▼
Edge Impulse AudioImpulseRunner (.eim model)
    │  drone confidence %
    ▼
Threshold check  ──── below threshold ──▶  meter display (no action)
    │
    │  above threshold + cooldown elapsed
    ▼
fswebcam snapshot
    │
    ▼
OpenClaw vision VLM
    │  JSON: action / drone_type / size / reason
    ▼
┌─────────────────────────────────────┐
│  ignore  │  log (CSV)  │  alert     │
│          │  LED on     │  LED on    │
│          │             │  Telegram  │
└─────────────────────────────────────┘
```

---

## Hardware

| Component | Details |
|---|---|
| Board | Qualcomm RUBIK Pi 3 |
| OS | Ubuntu (aarch64) |
| Microphone | USB microphone on default ALSA device |
| Camera | USB webcam on `/dev/video0` |
| LED | Connected to GPIO pin 571 |

---

## Requirements

### System packages

```bash
sudo apt install fswebcam python3-pip libportaudio2 libportaudiocpp0 portaudio19-dev
```

### Python packages

```bash
pip3 install edge_impulse_linux -i https://pypi.python.org/simple
pip3 install requests pyaudio opencv-python python-periphery
```

### OpenClaw

Install and configure [OpenClaw](https://github.com/lumosityfarm/openclaw) with a vision-capable model.

### Edge Impulse model

Download your trained `.eim` model from [Edge Impulse Studio](https://studio.edgeimpulse.com).  

---

## Configuration

All settings are at the top of `drone.py`:

| Variable | Default | Description |
|---|---|---|
| `confidenceThreshold` | `75.0` | Audio confidence % required to trigger visual check |
| `visualCooldownSeconds` | `360` | Minimum seconds between camera captures |
| `gpioPin` | `571` | GPIO pin number for the alert LED |
| `ledOnTime` | `3` | Seconds the LED stays on per alert |
| `telegramToken` | `""` | Telegram Bot API token |
| `telegramChatId` | `""` | Destination Telegram chat or channel ID |
| `openClawAgent` | `"main"` | OpenClaw agent name |
| `webcamDevice` | `"/dev/video0"` | USB webcam device path |
| `csvLogPath` | `"drone.csv"` | Local CSV detection log |

---

## Usage

### Directly

```bash
python3 drone.py /path/to/model.eim
python3 drone.py /path/to/model.eim --verbose
```

---

## Output

### Console — confidence meter

```
Drone: [────────────────        ]  42.0%
Drone: [████████████████████████]  87.3% 🚨 THRESHOLD EXCEEDED
```

### Console — visual analysis block

```
--- OPENCLAW VISUAL ANALYSIS ---
Drone visible : ✅ True
Model         : DJI Mini 4 Pro
Size          : small
Action        : 🚨 alert
Reasoning     : A small white quadcopter with a gimbal camera is visible flying at low altitude.
--------------------------------
```

### CSV log (`drone.csv`)

| timestamp | audio_confidence_pct | drone_type | action | snapshot_path |
|---|---|---|---|---|
| 2026-05-10 14:32:01 | 88.4 | DJI Mini 4 Pro | alert | /home/ubuntu/pic_20260510_143201.jpg |

### Telegram alert

```
🚨 ALERT - Drone detected
Model: DJI Mini 4 Pro
Size: small
Confidence: 88.40%
Reason: Small quadcopter visible at low altitude near perimeter.
```
---

## Demo

https://www.youtube.com/watch?v=togAkkwYE-E

---

## Complete tutorial
https://docs.edgeimpulse.com/projects/expert-network/multilayer-ai-agent-drone-detection-rubik-pi-3 

---

## Project Structure

```
├── drone.py      # Main detection script
├── drone.csv       # Detection log (auto-created on first run)
└── README.md # This file
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

