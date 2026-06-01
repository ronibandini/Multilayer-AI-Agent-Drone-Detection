# Drone Detection with Edge Impulse and OpenClaw 
# Roni Bandini @RoniBandini
# May 2026, MIT License

import argparse
import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
import requests
from periphery import GPIO
from edge_impulse_linux.audio import AudioImpulseRunner

# --- CLI arguments ---
parser = argparse.ArgumentParser(description="Drone Detection - RUBIK Pi 3")
parser.add_argument("model", nargs="?", default="model.eim",
                    help="Path to the .eim model file (default: model.eim)")
parser.add_argument("--verbose", action="store_true",
                    help="Print the raw OpenClaw response for every visual analysis")
args = parser.parse_args()

MODEL_FILE = args.model
VERBOSE    = args.verbose

# --- Configuration Settings ---
confidenceThreshold  = 70.0   # Min audio confidence % to trigger visual check
visualCooldownSeconds = 360    # Min secs between consecutive camera captures
gpioPin   = 571               # GPIO pin for physical LED alert on Rubik Pi 3
ledOnTime = 3                 # Seconds the LED or GPIO stays on

# --- Telegram Bot Config ---
telegramToken  = ""               # Put your Telegram Bot token here
telegramChatId = ""     # Destination chat or channel ID

# --- OpenClaw and Camera Config ---
openClawAgent = "main"            # Target agent name in OpenClaw config
webcamDevice  = "/dev/video0"     # OS path of the USB webcam
csvLogPath    = "drone.csv"       # Local CSV log file

# --- Prompt for Vision LLM Analysis ---
openClawPrompt = """
You are a drone surveillance expert with deep knowledge of UAV makes and models.

An audio classifier detected possible drone sound with {audio_confidence}% confidence.
Open and examine the image file located at: {image_path}

Instructions:
- Determine whether a drone or UAV is visible.
- If visible, identify the make and model from visual cues: body shape, rotor count and layout,
  arm design, colour scheme, camera gimbal, landing gear, and any visible markings.
  Be as specific as possible (e.g. "DJI Mini 4 Pro", "Autel EVO Lite+", "Parrot Anafi").
  If the exact model cannot be determined, give the closest match with a qualifier
  (e.g. "DJI Mavic series - exact model unclear").
- Estimate size relative to surroundings.
- Set action: "ignore" if no drone is visible, "log" if a drone is visible,
  "alert" if the drone is large or flying at low altitude in a restricted manner.
- Write a concise reasoning sentence explaining your conclusion.

Return ONLY valid JSON, no markdown, no explanation outside the JSON:

{{
  "action": "ignore|log|alert",
  "drone_visible": true,
  "drone_type": "<identified make and model>",
  "size": "small|medium|large",
  "reason": "<one sentence visual reasoning>"
}}
"""

csvHeaders = [
    "timestamp",
    "audio_confidence_pct",
    "drone_type",
    "action",
    "snapshot_path"
]

banner = r"""
██████╗ ██████╗  ██████╗ ███╗   ██╗███████╗
██╔══██╗██╔══██╗██╔═══██╗████╗  ██║██╔════╝
██║  ██║██████╔╝██║   ██║██╔██╗ ██║█████╗
██║  ██║██╔══██╗██║   ██║██║╚██╗██║██╔══╝
██████╔╝██║  ██║╚██████╔╝██║ ╚████║███████╗
╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝

██████╗ ███████╗████████╗███████╗ ██████╗████████╗██╗ ██████╗ ███╗   ██╗
██╔══██╗██╔════╝╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝██║██╔═══██╗████╗  ██║
██║  ██║█████╗     ██║   █████╗  ██║        ██║   ██║██║   ██║██╔██╗ ██║
██║  ██║██╔══╝     ██║   ██╔══╝  ██║        ██║   ██║██║   ██║██║╚██╗██║
██████╔╝███████╗   ██║   ███████╗╚██████╗   ██║   ██║╚██████╔╝██║ ╚████║
╚═════╝ ╚══════╝   ╚═╝   ╚══════╝ ╚═════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝

"""


try:
    outGpio = GPIO(gpioPin, "out")
    print(f"✓ GPIO pin {gpioPin} initialized as output.")
except Exception as e:
    outGpio = None
    print(f"⚠️ GPIO init error {gpioPin}: {e}")

METER_WIDTH = 40

def renderMeter(pct: float) -> str:
    filled = max(0, min(METER_WIDTH, int(round(pct / 100 * METER_WIDTH))))
    empty  = METER_WIDTH - filled
    if pct < confidenceThreshold:
        bar = "─" * filled + " " * empty
        flag = ""
    else:
        bar = "█" * filled + " " * empty
        flag = " 🚨 THRESHOLD EXCEEDED"
    return f"[{bar}] {pct:5.1f}%{flag}"


def initCsv():
    if not os.path.exists(csvLogPath):
        with open(csvLogPath, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=csvHeaders).writeheader()

def logToCsv(ts, conf, droneType, action, path):
    with open(csvLogPath, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=csvHeaders).writerow({
            "timestamp": ts,
            "audio_confidence_pct": conf,
            "drone_type": droneType,
            "action": action,
            "snapshot_path": path
        })

def sendTelegramMessage(message):
    if not telegramToken:
        return
    requests.post(
        f"https://api.telegram.org/bot{telegramToken}/sendMessage",
        json={"chat_id": telegramChatId, "text": message},
        timeout=10
    )

def captureDetectionImage():
    imagePath = f"/home/ubuntu/pic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    result = subprocess.run([
        "fswebcam", "-d", webcamDevice,
        "-r", "1280x720", "--no-banner",
        imagePath
    ])
    return imagePath if result.returncode == 0 else None

def analyzeImageWithOpenClaw(imagePath, audioConfidence):
    default = {
        "action": "ignore",
        "drone_visible": False,
        "drone_type": "Unknown",
        "size": "unknown",
        "reason": "",
        "raw_response": ""
    }
    cmd = [
        "/home/ubuntu/.npm-global/bin/openclaw", "agent",
        "--agent", openClawAgent,
        "-m", openClawPrompt.format(
            audio_confidence=round(audioConfidence, 2),
            image_path=imagePath
        ),
        "--json"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        print("  [OpenClaw] ⚠️  Command not found — is 'openclaw' installed and on PATH?")
        return default
    except Exception as e:
        print(f"  [OpenClaw] ⚠️  Failed to run: {e}")
        return default

    raw = result.stdout.strip()
    default["raw_response"] = raw

    try:
        envelope = json.loads(raw)
        payloads = envelope.get("result", {}).get("payloads", [])
        reply = (
            payloads[0]["text"]
            if payloads and isinstance(payloads[0].get("text"), str)
            else envelope.get("reply") or envelope.get("text") or raw
        )
    except Exception:
        reply = raw

    try:
        default.update(json.loads(reply))
    except Exception as e:
        print(f"  [OpenClaw] JSON parse failed: {e} — raw: {reply[:200]}")

    return default

def triggerAlertLed():
    if not outGpio:
        print("⚠️ GPIO not initialized")
        return
    try:
        outGpio.write(True)
        print(f"🟢 Alert LED activated on GPIO {gpioPin}")
        time.sleep(ledOnTime)
        outGpio.write(False)
        print("🔴 Alert LED deactivated")
    except Exception as e:
        print(f"GPIO error: {e}")
        try:
            outGpio.write(False)
        except Exception:
            pass

def processDetection(audioConfidencePct):
    imagePath = captureDetectionImage()
    if not imagePath:
        return

    analysis    = analyzeImageWithOpenClaw(imagePath, audioConfidencePct)
    droneVisible = analysis.get("drone_visible", False)
    droneType   = analysis.get("drone_type", "Unknown")
    size        = analysis.get("size", "unknown")
    reason      = analysis.get("reason", "")
    action      = analysis.get("action", "ignore")

    visibilityIcon = "✅" if droneVisible else "🟡"
    actionIcon     = {"ignore": "➖", "log": "📋", "alert": "🚨"}.get(action, "➖")

    print("\n--- OPENCLAW VISUAL ANALYSIS ---")
    print(f"Drone visible : {visibilityIcon} {droneVisible}")
    print(f"Model         : {droneType}")
    print(f"Size          : {size}")
    print(f"Action        : {actionIcon} {action}")
    if reason:
        print(f"Reasoning     : {reason}")
    if VERBOSE:
        raw = analysis.get("raw_response", "")
        print(f"\n[verbose] Raw OpenClaw response:\n{raw if raw else '(empty)'}")
    print("--------------------------------\n")

    if action == "ignore":
        return

    triggerAlertLed()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logToCsv(timestamp, audioConfidencePct, droneType, action, imagePath)

    if action in ["log", "alert"]:
        prefix = "🚨 ALERT" if action == "alert" else "📋 LOG"
        sendTelegramMessage(
            f"{prefix} - Drone Detection\n"
            f"Model: {droneType}\n"
            f"Size: {size}\n"
            f"Audio confidence: {audioConfidencePct:.2f}%\n"
            f"Reason: {reason or 'Not specified.'}"
        )


initCsv()

runner = None
lastDetectionTime = 0

def shutdown(sig=None, frame=None):
    print("\n\nStopping (CTRL-C).")
    if runner:
        runner.stop()
    try:
        if outGpio is not None:
            outGpio.write(False)
            outGpio.close()
            print(f"GPIO {gpioPin} closed.")
    except Exception:
        pass
    print("Execution ended.")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

with AudioImpulseRunner(MODEL_FILE) as runner:
    model_info = runner.init()
    labels     = model_info["model_parameters"]["labels"]
    print(f"✓ Model loaded. Labels: {labels}")
    print("")

    os.system('cls' if os.name == 'nt' else 'clear')
    print(banner)
    print("Roni Bandini, May 2026, Argentina, @RoniBandini")
    print(f"Model  : {MODEL_FILE}")
    print(f"Verbose: {'on' if VERBOSE else 'off'}  (use --verbose to enable raw OpenClaw output)")
    print("Monitoring for drone sounds...")
    print("Stop with CTRL-C")
    print("")

    for result, audio in runner.classifier():
        classifications = result["result"]["classification"]

        # Pull the drone confidence directly from the structured dict
        droneVal = classifications.get("drone", 0.0)
        dronePct = droneVal * 100 if droneVal <= 1.0 else droneVal

        print(f"\rDrone: {renderMeter(dronePct)}", end="", flush=True)

        if dronePct >= confidenceThreshold:
            now = time.time()
            if now - lastDetectionTime >= visualCooldownSeconds:
                lastDetectionTime = now
                print()   # newline before visual analysis block
                processDetection(dronePct)
