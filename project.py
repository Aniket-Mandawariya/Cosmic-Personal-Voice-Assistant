from __future__ import annotations

import argparse
import datetime as dt
import ctypes
import os
import random
import re
import time
import sys
import subprocess
import webbrowser
from dataclasses import dataclass
from urllib.parse import quote

try:
    import pyttsx3
except ImportError:  # pragma: no cover - optional dependency
    pyttsx3 = None

try:
    import speech_recognition as sr
except ImportError:  # pragma: no cover - optional dependency
    sr = None

try:
    import win32com.client as win32com_client
except ImportError:  # pragma: no cover - optional dependency
    win32com_client = None

try:
    import pyautogui
except ImportError:  # pragma: no cover - optional dependency
    pyautogui = None

try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover - optional dependency
    ImageGrab = None

try:
    import psutil
except ImportError:  # pragma: no cover - optional dependency
    psutil = None

try:
    import wikipedia
except ImportError:  # pragma: no cover - optional dependency
    wikipedia = None

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

from cosmic_engine import CosmicEngine, CosmicResponse


ASSISTANT_NAME = "Cosmic"
WAKE_WORDS = {"cosmic", "assistant", "alexa", "jarvis", "nova"}
FALLBACK_NAME = os.environ.get("USERNAME") or "there"
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")


@dataclass
class AssistantResponse:
    message: str
    should_exit: bool = False
    needs_confirmation: bool = False


class VoiceAssistant:
    def __init__(self, use_voice: bool = True) -> None:
        self.use_voice = use_voice and sr is not None
        self.command_engine = CosmicEngine(assistant_name=ASSISTANT_NAME, wake_words=WAKE_WORDS)
        self.engine = None
        self.sapi_voice = None
        self.recognizer = None
        self.microphone = None
        self._ambient_calibrated = False
        self.pending_action = ""
        self._listen_block_until = 0.0

        if self.use_voice:
            try:
                self.recognizer = sr.Recognizer()
                self.microphone = sr.Microphone()
            except Exception:
                self.use_voice = False
                self.recognizer = None
                self.microphone = None

        if pyttsx3 is not None:
            try:
                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", 162)
                self.engine.setProperty("volume", 1.0)
            except Exception:
                self.engine = None

        if os.name == "nt" and win32com_client is not None:
            try:
                self.sapi_voice = win32com_client.Dispatch("SAPI.SpVoice")
            except Exception:
                self.sapi_voice = None

    def speak(self, message: str, lang: str = "en") -> None:
        print(f"{ASSISTANT_NAME}: {message}")
        if lang == "hi":
            if self.speak_with_system_tts(message, lang):
                self._listen_block_until = max(self._listen_block_until, time.monotonic() + 0.45)
                return
        elif self.speak_with_sapi(message, lang):
            self._listen_block_until = max(self._listen_block_until, time.monotonic() + 0.45)
            return

        if self.engine is not None:
            try:
                self.engine.say(message)
                self.engine.runAndWait()
                self._listen_block_until = max(self._listen_block_until, time.monotonic() + 0.45)
                return
            except Exception:
                self.engine = None

        if self.speak_with_system_tts(message, lang):
            self._listen_block_until = max(self._listen_block_until, time.monotonic() + 0.45)

    @staticmethod
    def speak_with_system_tts(message: str, lang: str = "en") -> bool:
        if os.name != "nt":
            return False

        safe_message = message.replace("'", "''")
        if lang == "hi":
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "try { $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, "
                "[System.Speech.Synthesis.VoiceAge]::Adult, 0, "
                "[System.Globalization.CultureInfo]::GetCultureInfo('hi-IN')) } catch {} ; "
                "$s.Rate = -1; $s.Volume = 100; "
                f"$s.Speak('{safe_message}');"
            )
        else:
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "try { $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female, "
                "[System.Speech.Synthesis.VoiceAge]::Adult, 0, "
                "[System.Globalization.CultureInfo]::GetCultureInfo('en-US')) } catch {} ; "
                "$s.Rate = -1; $s.Volume = 100; "
                f"$s.Speak('{safe_message}');"
            )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
            )
            return True
        except Exception:
            return False

    def speak_with_sapi(self, message: str, lang: str = "en") -> bool:
        if self.sapi_voice is None:
            return False

        try:
            self._select_sapi_voice(lang)
            try:
                self.sapi_voice.Rate = -1
                self.sapi_voice.Volume = 100
            except Exception:
                pass
            self.sapi_voice.Speak(message, 0)
            return True
        except Exception:
            self.sapi_voice = None
            return False

    def _select_sapi_voice(self, lang: str) -> None:
        if self.sapi_voice is None:
            return

        target_terms = ["zira"] if lang == "en" else ["hindi", "indra", "kiran", "hema"]
        try:
            voices = self.sapi_voice.GetVoices()
        except Exception:
            return

        best_voice = None
        for index in range(getattr(voices, "Count", 0)):
            try:
                voice = voices.Item(index)
                description = str(voice.GetDescription()).lower()
            except Exception:
                continue
            if any(term in description for term in target_terms):
                best_voice = voice
                break

        if best_voice is not None:
            try:
                self.sapi_voice.Voice = best_voice
            except Exception:
                pass

    def listen(self, prompt: str | None = None, lang: str = "en") -> str:
        if not self.use_voice or self.recognizer is None or self.microphone is None:
            if prompt:
                print(prompt)
            return input(f"{FALLBACK_NAME}: ").strip().lower()

        if prompt:
            print(prompt)

        cooldown = self._listen_block_until - time.monotonic()
        if cooldown > 0:
            time.sleep(min(cooldown, 1.0))

        with self.microphone as source:
            if not self._ambient_calibrated:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.2)
                self._ambient_calibrated = True
            try:
                audio = self.recognizer.listen(source, timeout=3, phrase_time_limit=5)
            except sr.WaitTimeoutError:
                return ""

        try:
            text = self.recognizer.recognize_google(audio, language="hi-IN" if lang == "hi" else "en-US")
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            return ""
        return text.strip().lower()

    def greet(self) -> None:
        current_hour = dt.datetime.now().hour
        if current_hour < 12:
            greeting = "Good morning"
        elif current_hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        self.speak(f"{greeting}. I am {ASSISTANT_NAME}. Say my name and give a command.", self.command_engine.language)

    def run(self) -> None:
        self.greet()
        current_language = self.command_engine.language
        while True:
            self.announce_due_reminders(current_language)
            self.announce_due_alarms(current_language)
            self.announce_due_calendar_events(current_language)
            self.announce_due_timers(current_language)
            command = self.listen("Listening...", current_language)
            if not command:
                continue

            response = self.command_engine.process_command(command)
            if response is None:
                response = AssistantResponse("I did not get a response.")
            self.execute_response(response)
            if response.message:
                current_language = response.language if response.language != "en" or self.command_engine.language == "en" else self.command_engine.language
                self.speak(response.message, current_language)
                self.command_engine.record_interaction(command, response.message)
            for announcement in getattr(response, "announcements", []):
                self.speak(announcement, current_language)

            if response.should_exit:
                break

    def announce_due_reminders(self, lang: str = "en") -> None:
        for reminder in self.command_engine.pop_due_reminders():
            self.speak(reminder, lang)

    def announce_due_alarms(self, lang: str = "en") -> None:
        for alarm in self.command_engine.pop_due_alarms():
            self.speak(alarm, lang)

    def announce_due_calendar_events(self, lang: str = "en") -> None:
        for event in self.command_engine.pop_due_calendar_events():
            self.speak(event, lang)

    def announce_due_timers(self, lang: str = "en") -> None:
        for timer in self.command_engine.pop_due_timers():
            self.speak(timer, lang)

    def execute_response(self, response: CosmicResponse) -> None:
        action = response.action
        if not action:
            return

        if action == "open_url":
            url = response.data.get("url", "")
            if url:
                webbrowser.open(url)
            return

        if action == "open_app":
            app_name = response.data.get("app_name", "")
            if app_name:
                self.open_app(app_name)
            return

        if action == "open_path":
            path = response.data.get("path", "")
            if path:
                self.open_target(path)
            return

        if action == "save_note":
            note = response.data.get("note", "")
            if note:
                self.save_note(note)
            return

        if action == "run_macro":
            macro = response.data.get("macro", "")
            if macro:
                self.run_macro(macro)
            return

        if action == "set_clipboard":
            text = response.data.get("text", "")
            if text:
                self.set_clipboard(text)
            return

        if action == "set_clipboard_and_paste":
            text = response.data.get("text", "")
            if text:
                self.set_clipboard(text)
                self.paste_clipboard()
            return

        if action == "read_clipboard":
            response.message = self.read_clipboard_message(response.message)
            return

        if action == "paste_clipboard":
            self.paste_clipboard()
            return

        if action == "save_screenshot":
            self.save_screenshot(response)
            return

        if action == "type_text":
            text = response.data.get("text", "")
            if text and pyautogui is not None:
                try:
                    pyautogui.write(text, interval=0.01)
                except Exception:
                    pass
            return

        if action == "press_key":
            key = response.data.get("key", "")
            if key and pyautogui is not None:
                try:
                    pyautogui.press(key)
                except Exception:
                    pass
            return

        if action == "hotkey":
            keys = response.data.get("keys", "")
            if keys and pyautogui is not None:
                combo = [part.strip() for part in keys.split(",") if part.strip()]
                if combo:
                    try:
                        pyautogui.hotkey(*combo)
                    except Exception:
                        pass
            return

        if action == "scroll_page":
            direction = response.data.get("direction", "")
            amount = response.data.get("amount", "")
            if direction and amount:
                self.scroll_page(direction, amount)
            return

        if action == "move_mouse":
            direction = response.data.get("direction", "")
            amount = response.data.get("amount", "")
            if direction and amount:
                self.move_mouse(direction, amount)
            return

        if action == "mouse_click":
            button = response.data.get("button", "")
            clicks = response.data.get("clicks", "")
            if button and clicks:
                self.mouse_click(button, clicks)
            return

        if action == "lock_system":
            self.lock_system()
            return

        if action == "show_desktop":
            self.show_desktop()
            return

        if action == "close_active_window":
            self.close_active_window()
            return

        if action == "adjust_volume":
            direction = response.data.get("direction", "")
            if direction:
                self.adjust_volume(direction)
            return

        if action == "set_volume":
            level = response.data.get("level", "")
            if level:
                self.set_volume(level)
            return

        if action == "adjust_brightness":
            direction = response.data.get("direction", "")
            if direction:
                self.adjust_brightness(direction)
            return

        if action == "set_brightness":
            level = response.data.get("level", "")
            if level:
                self.set_brightness(level)
            return

        if action == "close_process":
            name = response.data.get("name", "")
            if name:
                self.close_process(name)
            return

        if action == "sleep_system":
            self.sleep_system()
            return

        if action == "restart_system":
            self.restart_system()
            return

        if action == "shutdown_system":
            self.shutdown_system()
            return

        if action == "logoff_system":
            self.logoff_system()
            return

    def handle_command(self, command: str) -> AssistantResponse:
        normalized = self.normalize_command(command)
        if not normalized:
            return AssistantResponse("I did not catch that.")

        if self.pending_action == "whatsapp_chat":
            response = self.open_whatsapp_chat(normalized)
            if response and ("opening whatsapp chat" in response.message.lower() or "opened whatsapp web" in response.message.lower()):
                self.pending_action = ""
            return response

        if normalized in {"exit", "quit", "stop", "goodbye", "bye"}:
            return AssistantResponse("Goodbye. I will be here when you need me.", should_exit=True)

        if "time" in normalized:
            now = dt.datetime.now().strftime("%I:%M %p")
            return AssistantResponse(f"The time is {now}.")

        if "date" in normalized or "day" in normalized:
            today = dt.datetime.now().strftime("%A, %B %d, %Y")
            return AssistantResponse(f"Today is {today}.")

        wiki_response = self.handle_wikipedia_command(normalized)
        if wiki_response is not None:
            return wiki_response

        system_response = self.handle_system_command(normalized)
        if system_response is not None:
            return system_response

        if normalized.startswith("search "):
            query = normalized.removeprefix("search ").strip()
            if query:
                url = "https://www.google.com/search?q=" + quote(query)
                webbrowser.open(url)
                return AssistantResponse(f"Searching for {query}.")

        if normalized.startswith("open "):
            target = normalized.removeprefix("open ").strip()
            return self.open_target(target)

        if normalized.startswith("play "):
            query = normalized.removeprefix("play ").strip()
            if query:
                url = "https://www.youtube.com/results?search_query=" + quote(query)
                webbrowser.open(url)
                return AssistantResponse(f"Searching YouTube for {query}.")

        if normalized.startswith("note "):
            note = normalized.removeprefix("note ").strip()
            if note:
                self.save_note(note)
                return AssistantResponse("I saved that note.")

        if "joke" in normalized:
            return AssistantResponse(random.choice(self.jokes()))

        if "help" in normalized or "commands" in normalized:
            return AssistantResponse(self.help_text())

        if "who are you" in normalized or "your name" in normalized:
            return AssistantResponse(f"I am {ASSISTANT_NAME}, your personal assistant.")

        return AssistantResponse(
            "I can tell the time or date, look up Wikipedia, open websites and apps, search the web, play YouTube results, save notes, and control system actions."
        )

    def handle_wikipedia_command(self, normalized: str) -> AssistantResponse | None:
        if normalized.startswith("wikipedia "):
            topic = normalized.removeprefix("wikipedia ").strip()
            return self.wikipedia_lookup(topic)

        if normalized.startswith("wiki "):
            topic = normalized.removeprefix("wiki ").strip()
            return self.wikipedia_lookup(topic)

        if normalized.startswith("who is "):
            topic = normalized.removeprefix("who is ").strip()
            return self.wikipedia_lookup(topic)

        if normalized.startswith("what is "):
            topic = normalized.removeprefix("what is ").strip()
            return self.wikipedia_lookup(topic)

        return None

    def wikipedia_lookup(self, topic: str) -> AssistantResponse:
        if not topic:
            return AssistantResponse("Tell me what topic you want me to search on Wikipedia.")

        if wikipedia is None:
            return AssistantResponse("Wikipedia support is not installed. Please install the wikipedia package.")

        try:
            summary = wikipedia.summary(topic, sentences=2, auto_suggest=True, redirect=True)
            return AssistantResponse(summary)
        except wikipedia.DisambiguationError as exc:  # type: ignore[attr-defined]
            options = ", ".join(exc.options[:5])
            return AssistantResponse(f"That topic is ambiguous. Try one of these: {options}.")
        except wikipedia.PageError:  # type: ignore[attr-defined]
            return AssistantResponse(f"I could not find a Wikipedia page for {topic}.")
        except Exception:
            return AssistantResponse(f"I could not fetch Wikipedia results for {topic}.")

    def handle_system_command(self, normalized: str) -> AssistantResponse | None:
        if normalized in {"lock", "lock pc", "lock system"}:
            self.lock_system()
            return AssistantResponse("Locking the system.")

        if normalized in {"sleep", "sleep pc", "sleep system"}:
            self.pending_action = "sleep"
            return AssistantResponse(
                "Do you want me to put the system to sleep? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"restart", "restart pc", "reboot"}:
            self.pending_action = "restart"
            return AssistantResponse(
                "Do you want me to restart the system? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"shutdown", "shut down", "power off"}:
            self.pending_action = "shutdown"
            return AssistantResponse(
                "Do you want me to shut down the system? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"log off", "logoff", "sign out"}:
            self.pending_action = "logoff"
            return AssistantResponse(
                "Do you want me to log off the current user? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"minimize all", "show desktop", "desktop"}:
            self.show_desktop()
            return AssistantResponse("Showing the desktop.")

        if normalized in {"task manager", "open task manager"}:
            self.open_app("taskmgr")
            return AssistantResponse("Opening Task Manager.")

        if normalized in {"volume up", "louder"}:
            self.adjust_volume("up")
            return AssistantResponse("Volume up.")

        if normalized in {"volume down", "lower volume"}:
            self.adjust_volume("down")
            return AssistantResponse("Volume down.")

        if normalized in {"mute", "unmute"}:
            self.adjust_volume("mute")
            return AssistantResponse("Toggling mute.")

        if normalized.startswith("open "):
            target = normalized.removeprefix("open ").strip()
            app_response = self.open_app_or_target(target)
            if app_response is not None:
                return app_response

        if normalized.startswith("close "):
            target = normalized.removeprefix("close ").strip()
            if target in {"window", "app", "application"}:
                self.close_active_window()
                return AssistantResponse("Closing the active window.")
            if target:
                return self.close_process(target)

        return None

    def handle_confirmation(self, command: str) -> AssistantResponse:
        normalized = self.normalize_command(command)
        if normalized in {"yes", "confirm", "do it", "ok", "okay"}:
            action = self.pending_action
            self.pending_action = ""
            if action == "shutdown":
                self.shutdown_system()
                return AssistantResponse("Shutting down the system now.", should_exit=True)
            if action == "restart":
                self.restart_system()
                return AssistantResponse("Restarting the system now.", should_exit=True)
            if action == "sleep":
                self.sleep_system()
                return AssistantResponse("Putting the system to sleep now.", should_exit=True)
            if action == "logoff":
                self.logoff_system()
                return AssistantResponse("Logging off now.", should_exit=True)

        if normalized in {"no", "cancel", "stop", "never mind", "nevermind"}:
            self.pending_action = ""
            return AssistantResponse("Cancelled.")

        return AssistantResponse("Please say yes or no.")

    @staticmethod
    def normalize_command(command: str) -> str:
        cleaned = command.lower().strip()
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        for wake in WAKE_WORDS:
            cleaned = re.sub(rf"\b{re.escape(wake)}\b", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def open_target(self, target: str) -> AssistantResponse:
        if not target:
            return AssistantResponse("Tell me what to open.")

        if target in {"screenshots folder", "screenshot folder", "screenshots"}:
            path = SCREENSHOTS_DIR
            try:
                os.makedirs(path, exist_ok=True)
                os.startfile(path)  # type: ignore[attr-defined]
                return AssistantResponse("Opening the screenshots folder.")
            except Exception:
                return AssistantResponse("I could not open the screenshots folder.")

        if target.startswith("whatsapp chat with "):
            contact = target.removeprefix("whatsapp chat with ").strip()
            return self.open_whatsapp_chat(contact)

        websites = {
            "google": "https://www.google.com",
            "youtube": "https://www.youtube.com",
            "gmail": "https://mail.google.com",
            "github": "https://github.com",
            "whatsapp": "https://web.whatsapp.com",
            "whatsapp web": "https://web.whatsapp.com",
            "telegram": "https://web.telegram.org",
            "discord": "https://discord.com/app",
            "spotify": "https://open.spotify.com",
            "teams": "https://teams.microsoft.com",
            "slack": "https://slack.com/client",
            "zoom": "https://zoom.us",
        }

        if target in websites:
            webbrowser.open(websites[target])
            return AssistantResponse(f"Opening {target}.")

        path = os.path.expanduser(target)
        if os.path.exists(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
                return AssistantResponse(f"Opening {target}.")
            except OSError:
                pass

        webbrowser.open(f"https://www.google.com/search?q={quote(target)}")
        return AssistantResponse(f"Searching for {target}.")

    def open_whatsapp_chat(self, contact: str) -> AssistantResponse:
        if not contact:
            self.pending_action = "whatsapp_chat"
            return AssistantResponse("Tell me the contact name or phone number for WhatsApp.")

        digits = re.sub(r"\D", "", contact)
        if len(digits) >= 7:
            webbrowser.open(f"https://wa.me/{digits}")
            return AssistantResponse(f"Opening WhatsApp chat with {contact}.")

        contacts_file = os.path.join(os.path.dirname(__file__), "contacts.json")
        if os.path.exists(contacts_file):
            try:
                import json

                with open(contacts_file, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                lookup = contact.lower().strip()
                if isinstance(payload, dict) and lookup in payload:
                    number = str(payload[lookup]).strip()
                    number = re.sub(r"\D", "", number)
                    if number:
                        webbrowser.open(f"https://wa.me/{number}")
                        return AssistantResponse(f"Opening WhatsApp chat with {contact}.")
                if isinstance(payload, list):
                    for item in payload:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("name", "")).strip().lower()
                        number = re.sub(r"\D", "", str(item.get("number", "")).strip())
                        if contact.lower().strip() in name and number:
                            webbrowser.open(f"https://wa.me/{number}")
                            return AssistantResponse(f"Opening WhatsApp chat with {name}.")
            except Exception:
                pass

        webbrowser.open("https://web.whatsapp.com")
        self.pending_action = "whatsapp_chat"
        return AssistantResponse("I couldn’t find that contact. Say the phone number directly, or add the person to contacts.json.")

    def open_app_or_target(self, target: str) -> AssistantResponse | None:
        if not target:
            return AssistantResponse("Tell me what to open.")

        apps = {
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "calc": ["calc.exe"],
            "cmd": ["cmd.exe"],
            "command prompt": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "file explorer": ["explorer.exe"],
            "explorer": ["explorer.exe"],
            "paint": ["mspaint.exe"],
            "task manager": ["taskmgr.exe"],
            "chrome": ["chrome.exe"],
            "google chrome": ["chrome.exe"],
            "edge": ["msedge.exe"],
            "microsoft edge": ["msedge.exe"],
            "word": ["WINWORD.EXE"],
            "excel": ["EXCEL.EXE"],
            "powerpoint": ["POWERPNT.EXE"],
            "outlook": ["OUTLOOK.EXE"],
            "whatsapp": ["whatsapp.exe"],
            "discord": ["Discord.exe"],
            "spotify": ["Spotify.exe"],
            "telegram": ["Telegram.exe"],
            "teams": ["ms-teams.exe"],
            "zoom": ["Zoom.exe"],
            "slack": ["slack.exe"],
        }

        if target in apps:
            self.open_app(apps[target][0])
            return AssistantResponse(f"Opening {target}.")

        return self.open_target(target)

    @staticmethod
    def open_app(app_name: str) -> None:
        try:
            os.startfile(app_name)  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen([app_name], shell=True)

    @staticmethod
    def lock_system() -> None:
        if os.name == "nt":
            try:
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
            except Exception:
                pass

    @staticmethod
    def show_desktop() -> None:
        if pyautogui is not None:
            try:
                pyautogui.hotkey("win", "d")
                return
            except Exception:
                pass

    @staticmethod
    def close_active_window() -> None:
        if pyautogui is not None:
            try:
                pyautogui.hotkey("alt", "f4")
            except Exception:
                pass

    @staticmethod
    def adjust_volume(direction: str) -> None:
        if os.name != "nt":
            if pyautogui is None:
                return
            try:
                if direction == "up":
                    pyautogui.press("volumeup", presses=3)
                elif direction == "down":
                    pyautogui.press("volumedown", presses=3)
                elif direction == "mute":
                    pyautogui.press("volumemute")
            except Exception:
                pass
            return

        vk_map = {
            "up": 0xAF,
            "down": 0xAE,
            "mute": 0xAD,
        }
        vk_code = vk_map.get(direction)
        if vk_code is not None:
            try:
                for _ in range(6 if direction in {"up", "down"} else 1):
                    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(vk_code, 0, 0x0002, 0)
                return
            except Exception:
                pass

        if pyautogui is None:
            return
        try:
            if direction == "up":
                pyautogui.press("volumeup", presses=6)
            elif direction == "down":
                pyautogui.press("volumedown", presses=6)
            elif direction == "mute":
                pyautogui.press("volumemute")
        except Exception:
            pass

    @staticmethod
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

        if pyautogui is None:
            return

        try:
            current = 50
            steps = max(0, int((target - current) / 2))
            key = "volumeup" if target >= current else "volumedown"
            if steps:
                pyautogui.press(key, presses=abs(steps))
        except Exception:
            pass

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def sleep_system() -> None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    check=False,
                )
            except Exception:
                pass

    @staticmethod
    def restart_system() -> None:
        if os.name == "nt":
            os.system("shutdown /r /t 5")

    @staticmethod
    def shutdown_system() -> None:
        if os.name == "nt":
            os.system("shutdown /s /t 5")

    @staticmethod
    def logoff_system() -> None:
        if os.name == "nt":
            os.system("shutdown /l")

    @staticmethod
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
                pass
        if pyautogui is not None:
            try:
                pyautogui.write(content, interval=0.01)
            except Exception:
                pass

    @staticmethod
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
                return ""
        return ""

    @classmethod
    def read_clipboard_message(cls, fallback: str = "") -> str:
        content = cls.get_clipboard_text()
        if content:
            return f"Clipboard contains: {content}"
        return fallback or "Clipboard is empty."

    @staticmethod
    def paste_clipboard() -> None:
        if pyautogui is None:
            return
        try:
            pyautogui.hotkey("ctrl", "v")
        except Exception:
            pass

    def save_screenshot(self, response: CosmicResponse) -> None:
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

    def run_macro(self, macro: str) -> None:
        name = macro.lower().strip()
        if name == "study":
            self.open_app_or_target("notepad")
            self.open_app_or_target("calculator")
            self.adjust_volume("down")
            self.set_brightness(45)
            return
        if name == "work":
            self.open_app_or_target("chrome")
            self.open_app_or_target("outlook")
            self.open_app_or_target("teams")
            self.set_volume(45)
            return
        if name == "bedtime":
            self.adjust_volume("mute")
            self.set_brightness(20)
            return
        if name == "focus":
            self.open_app_or_target("notepad")
            self.adjust_volume("mute")
            self.set_brightness(40)
            return
        if name == "normal":
            self.set_volume(50)
            self.set_brightness(60)
            return
        if name == "relax":
            webbrowser.open("https://music.youtube.com")
            self.set_volume(40)
            self.set_brightness(60)
            return

    def close_process(self, name: str) -> AssistantResponse:
        if psutil is None:
            return AssistantResponse("Process control is not installed.")

        killed = 0
        needle = name.lower().replace(".exe", "").strip()
        for proc in psutil.process_iter(["name"]):
            proc_name = (proc.info.get("name") or "").lower()
            if needle and needle in proc_name:
                try:
                    proc.terminate()
                    killed += 1
                except Exception:
                    pass

        if killed:
            return AssistantResponse(f"Closed {killed} process{'es' if killed != 1 else ''}.")
        return AssistantResponse(f"I could not find a running process named {name}.")

    def save_note(self, note: str) -> None:
        notes_dir = os.path.join(os.path.dirname(__file__), "notes")
        os.makedirs(notes_dir, exist_ok=True)
        file_name = dt.datetime.now().strftime("note-%Y-%m-%d.txt")
        file_path = os.path.join(notes_dir, file_name)
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        with open(file_path, "a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {note}\n")

    @staticmethod
    def jokes() -> list[str]:
        return [
            "Why did the computer go to the doctor? It caught a virus.",
            "I would tell you a UDP joke, but you might not get it.",
            "Why do programmers prefer dark mode? Because light attracts bugs.",
        ]

    @staticmethod
    def help_text() -> str:
        return (
            "Quick guide: time and date; search and Wikipedia; notes and reminders; alarms, timers, and stopwatch; "
            "clipboard history; screenshots; translate text; focus mode; volume and brightness; typing and keyboard shortcuts; "
            "open apps and websites; call and WhatsApp; or say help for the full command list."
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Personal voice assistant.")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Force text mode instead of voice mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    assistant = VoiceAssistant(use_voice=not args.text)
    print(assistant.command_engine.startup_status_message())
    if not assistant.use_voice:
        print("Voice mode is unavailable or disabled. Running in text mode.")
        print("Type commands like: time, open youtube, search python, note hello, or exit.")

    try:
        assistant.run()
    except KeyboardInterrupt:
        print("\nGoodbye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
