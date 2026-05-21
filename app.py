from __future__ import annotations

import datetime as dt
import ctypes
import logging
import os
import subprocess
import webbrowser

from flask import Flask, jsonify, render_template, request

from cosmic_engine import CosmicEngine, CosmicResponse

try:
    import pyautogui
except ImportError:  # pragma: no cover - optional dependency
    pyautogui = None

try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover - optional dependency
    ImageGrab = None

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
except ImportError:  # pragma: no cover - optional dependency
    AudioUtilities = None
    IAudioEndpointVolume = None
    CLSCTX_ALL = None

try:
    import screen_brightness_control as screen_brightness_control
except ImportError:  # pragma: no cover - optional dependency
    screen_brightness_control = None


ASSISTANT_NAME = "Cosmic"
APP_ROOT = os.path.dirname(__file__)
NOTES_DIR = os.path.join(APP_ROOT, "notes")
SCREENSHOTS_DIR = os.path.join(APP_ROOT, "screenshots")
logger = logging.getLogger(__name__)

app = Flask(__name__)
engine = CosmicEngine(assistant_name=ASSISTANT_NAME)


def execute_action(response: CosmicResponse | None) -> None:
    if response is None:
        logger.warning("execute_action received no response")
        return

    action = response.action
    if not action:
        return

    if action == "open_url":
        return

    if action == "save_note":
        note = response.data.get("note", "").strip()
        if note:
            os.makedirs(NOTES_DIR, exist_ok=True)
            file_name = os.path.join(NOTES_DIR, "notes.txt")
            try:
                with open(file_name, "a", encoding="utf-8") as file:
                    file.write(note + "\n")
            except Exception:
                logger.exception("Failed to save note to %s", file_name)
        return

    if action == "type_text":
        text = response.data.get("text", "").strip()
        if text and pyautogui is not None:
            try:
                pyautogui.write(text, interval=0.01)
            except Exception:
                logger.exception("Failed to type text")
        return

    if action == "press_key":
        key = response.data.get("key", "").strip()
        if key and pyautogui is not None:
            try:
                pyautogui.press(key)
            except Exception:
                logger.exception("Failed to press key %s", key)
        return

    if action == "hotkey":
        keys = response.data.get("keys", "").strip()
        if keys and pyautogui is not None:
            combo = [part.strip() for part in keys.split(",") if part.strip()]
            if combo:
                try:
                    pyautogui.hotkey(*combo)
                except Exception:
                    logger.exception("Failed to send hotkey %s", combo)
        return

    if action == "scroll_page":
        direction = response.data.get("direction", "").strip()
        amount = response.data.get("amount", "").strip()
        if direction and amount:
            scroll_page(direction, amount)
        return

    if action == "move_mouse":
        direction = response.data.get("direction", "").strip()
        amount = response.data.get("amount", "").strip()
        if direction and amount:
            move_mouse(direction, amount)
        return

    if action == "mouse_click":
        button = response.data.get("button", "").strip()
        clicks = response.data.get("clicks", "").strip()
        if button and clicks:
            mouse_click(button, clicks)
        return

    if action == "set_volume":
        level = response.data.get("level", "").strip()
        if level:
            set_volume(level)
        return

    if action == "adjust_brightness":
        direction = response.data.get("direction", "").strip()
        if direction:
            adjust_brightness(direction)
        return

    if action == "set_brightness":
        level = response.data.get("level", "").strip()
        if level:
            set_brightness(level)
        return

    if action == "set_clipboard":
        text = response.data.get("text", "").strip()
        if text:
            set_clipboard(text)
        return

    if action == "set_clipboard_and_paste":
        text = response.data.get("text", "").strip()
        if text:
            set_clipboard(text)
            paste_clipboard()
        return

    if action == "read_clipboard":
        response.message = read_clipboard_message(response.message)
        return

    if action == "paste_clipboard":
        paste_clipboard()
        return

    if os.name != "nt":
        return

    if action == "lock_system":
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
        return

    if action == "show_desktop":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys('^{ESC}');",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return

    if action == "open_app":
        app_name = response.data.get("app_name", "").strip()
        if app_name:
            try:
                os.startfile(app_name)  # type: ignore[attr-defined]
            except Exception:
                try:
                    subprocess.Popen([app_name], shell=True)
                except Exception:
                    logger.exception("Failed to open app %s", app_name)
        return

    if action == "open_path":
        path = response.data.get("path", "").strip()
        if path:
            if os.path.normpath(path) == os.path.normpath(SCREENSHOTS_DIR):
                open_screenshots_folder()
                return
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Failed to open path %s", path)
        return

    if action == "adjust_volume":
        direction = response.data.get("direction", "")
        if direction in {"up", "down", "mute"}:
            adjust_volume(direction)
        return

    if action == "close_active_window":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys('%{F4}')",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return

    if action == "close_process":
        name = response.data.get("name", "").strip()
        if name:
            subprocess.run(["taskkill", "/f", "/im", name], check=False, capture_output=True, text=True)
        return

    if action == "sleep_system":
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)
        return

    if action == "restart_system":
        subprocess.run(["shutdown", "/r", "/t", "5"], check=False)
        return

    if action == "shutdown_system":
        subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
        return

    if action == "logoff_system":
        subprocess.run(["shutdown", "/l"], check=False)
        return

def set_volume(level: str | int) -> None:
    try:
        target = max(0, min(100, int(level)))
    except Exception:
        return

    if AudioUtilities is not None and IAudioEndpointVolume is not None and CLSCTX_ALL is not None:
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(target / 100.0, None)
            return
        except Exception:
            pass

    if os.name == "nt":
        try:
            current = 50
            steps = max(0, int(abs(target - current) / 2))
            vk_code = 0xAF if target >= current else 0xAE
            for _ in range(steps):
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk_code, 0, 0x0002, 0)
            return
        except Exception:
            pass

    if pyautogui is None:
        return

    try:
        current = 50
        steps = max(0, int(abs(target - current) / 2))
        key = "volumeup" if target >= current else "volumedown"
        if steps:
            pyautogui.press(key, presses=steps)
    except Exception:
        pass


def adjust_volume(direction: str) -> None:
    if os.name == "nt":
        try:
            vk_code = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}.get(direction)
            if vk_code is not None:
                presses = 6 if direction in {"up", "down"} else 1
                for _ in range(presses):
                    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(vk_code, 0, 0x0002, 0)
                return
        except Exception:
            pass

    if pyautogui is not None:
        try:
            if direction == "up":
                pyautogui.press("volumeup", presses=6)
            elif direction == "down":
                pyautogui.press("volumedown", presses=6)
            elif direction == "mute":
                pyautogui.press("volumemute")
        except Exception:
            pass


def adjust_brightness(direction: str) -> None:
    if screen_brightness_control is None:
        if os.name != "nt":
            return
        try:
            current = 50
            target = min(100, current + 10) if direction == "up" else max(0, current - 10)
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods | ForEach-Object {{ $_.WmiSetBrightness(1, {target}) }}",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass
        return
    try:
        current = int(screen_brightness_control.get_brightness(display=0)[0])
        if direction == "up":
            screen_brightness_control.set_brightness(min(100, current + 10), display=0)
        elif direction == "down":
            screen_brightness_control.set_brightness(max(0, current - 10), display=0)
    except Exception:
        pass


def set_brightness(level: str | int) -> None:
    if screen_brightness_control is None:
        if os.name != "nt":
            return
        try:
            target = max(0, min(100, int(level)))
        except Exception:
            return
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods | ForEach-Object {{ $_.WmiSetBrightness(1, {target}) }}",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass
        return
    try:
        target = max(0, min(100, int(level)))
    except Exception:
        return
    try:
        screen_brightness_control.set_brightness(target, display=0)
    except Exception:
        pass


def scroll_page(direction: str, amount: str | int) -> None:
    if pyautogui is None:
        return
    try:
        steps = max(1, int(amount))
    except Exception:
        steps = 5
    delta = steps * 8
    if direction == "down":
        delta = -delta
    try:
        pyautogui.scroll(delta)
    except Exception:
        pass


def move_mouse(direction: str, amount: str | int) -> None:
    if pyautogui is None:
        return
    try:
        pixels = max(1, int(amount))
    except Exception:
        pixels = 100
    dx = dy = 0
    if direction == "up":
        dy = -pixels
    elif direction == "down":
        dy = pixels
    elif direction == "left":
        dx = -pixels
    elif direction == "right":
        dx = pixels
    try:
        pyautogui.moveRel(dx, dy, duration=0.1)
    except Exception:
        pass


def mouse_click(button: str, clicks: str | int) -> None:
    if pyautogui is None:
        return
    try:
        count = max(1, int(clicks))
    except Exception:
        count = 1
    try:
        pyautogui.click(button=button, clicks=count, interval=0.1)
    except Exception:
        pass


def open_app(app_name: str) -> None:
    try:
        os.startfile(app_name)  # type: ignore[attr-defined]
    except Exception:
        try:
            subprocess.Popen([app_name], shell=True)
        except Exception:
            pass


def open_screenshots_folder() -> None:
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    try:
        os.startfile(SCREENSHOTS_DIR)  # type: ignore[attr-defined]
    except Exception:
        subprocess.Popen(["explorer", SCREENSHOTS_DIR], shell=True)


def save_screenshot(response: CosmicResponse) -> None:
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    file_name = os.path.join(SCREENSHOTS_DIR, f"screenshot_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

    if pyautogui is not None:
        try:
            image = pyautogui.screenshot()
            image.save(file_name)
            response.message = f"Saved screenshot to {file_name}."
            return
        except Exception:
            pass

    if ImageGrab is not None:
        try:
            image = ImageGrab.grab(all_screens=True)
            image.save(file_name)
            response.message = f"Saved screenshot to {file_name}."
            return
        except Exception:
            pass

    response.message = "I could not take a screenshot. Install Pillow or pyautogui if needed."


def set_clipboard(text: str) -> None:
    content = text.strip()
    if not content:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                input=content,
                text=True,
                check=False,
                capture_output=True,
            )
            return
        except Exception:
            logger.exception("Failed to set clipboard text")


def get_clipboard_text() -> str:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "[Console]::Out.Write((Get-Clipboard -Raw))"],
                check=False,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except Exception:
            logger.exception("Failed to read clipboard text")
            return ""
    return ""


def read_clipboard_message(fallback: str = "") -> str:
    content = get_clipboard_text()
    if content:
        return f"Clipboard contains: {content}"
    return fallback or "Clipboard is empty."


def paste_clipboard() -> None:
    if pyautogui is None:
        return
    try:
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        logger.exception("Failed to paste clipboard")


def run_macro(macro: str) -> None:
    name = macro.lower().strip()
    if name == "study":
        open_app("notepad.exe")
        open_app("calc.exe")
        adjust_volume("down")
        set_brightness(45)
        return
    if name == "work":
        open_app("chrome.exe")
        open_app("OUTLOOK.EXE")
        open_app("ms-teams.exe")
        set_volume(45)
        return
    if name == "bedtime":
        adjust_volume("mute")
        set_brightness(20)
        return
    if name == "focus":
        open_app("notepad.exe")
        adjust_volume("mute")
        set_brightness(40)
        return
    if name == "normal":
        set_volume(50)
        set_brightness(60)
        return
    if name == "relax":
        webbrowser.open("https://music.youtube.com")
        set_volume(40)
        set_brightness(60)
        return


@app.get("/")
def home():
    return render_template(
        "index.html",
        assistant_name=ASSISTANT_NAME,
        startup_status=engine.startup_status_message(),
    )


@app.post("/api/command")
def api_command():
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip()
    try:
        response = engine.process_command(command)
        if response is None:
            response = CosmicResponse(message="I did not get a response.", language=engine.language)
        execute_action(response)
        announcements = (
            engine.pop_due_alarms()
            + engine.pop_due_reminders()
            + engine.pop_due_calendar_events()
            + engine.pop_due_timers()
        )
        if command and response.message:
            engine.record_interaction(command, response.message)
        return jsonify(
            {
                "message": response.message,
                "should_exit": response.should_exit,
                "needs_confirmation": response.needs_confirmation,
                "action": response.action,
                "data": response.data,
                "announcements": announcements + getattr(response, "announcements", []),
                "language": response.language if response.language != "en" or engine.language == "en" else engine.language,
            }
        )
    except Exception:
        logger.exception("Failed to process command: %s", command)
        return (
            jsonify(
                {
                    "message": "Sorry, something went wrong while processing that command.",
                    "should_exit": False,
                    "needs_confirmation": False,
                    "action": "",
                    "data": {},
                    "announcements": [],
                    "language": engine.language,
                }
            ),
            500,
        )


@app.get("/api/ping")
def ping():
    return jsonify({"status": "ok", "assistant": ASSISTANT_NAME})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
