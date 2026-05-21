from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import logging
import json
import os
import random
import re
import unicodedata
from typing import Optional
from urllib.parse import quote
import urllib.request

try:
    import wikipedia
except ImportError:  # pragma: no cover - optional dependency
    wikipedia = None


logger = logging.getLogger(__name__)

@dataclass
class CosmicResponse:
    message: str = ""
    should_exit: bool = False
    needs_confirmation: bool = False
    action: str = ""
    data: dict[str, str] = field(default_factory=dict)
    announcements: list[str] = field(default_factory=list)
    language: str = "en"

class CosmicEngine:
    def __init__(
        self,
        assistant_name: str = "Cosmic",
        wake_words: Optional[set[str]] = None,
    ) -> None:
        self.assistant_name = assistant_name
        self.wake_words = wake_words or {"cosmic", "assistant", "alexa", "jarvis", "nova"}
        self.pending_action = ""
        self.pending_contact_name = ""
        self.pending_contact_number = ""
        self.pending_message_text = ""
        self.contacts = self._load_contacts()
        self.memory = self._load_memory()
        self.reminders = self._load_reminders()
        self.alarms = self._load_alarms()
        self.calendar_events = self._load_calendar_events()
        self.timers = self._load_timers()
        self.clipboard_history = self._load_clipboard_history()
        self.last_file_search_results: list[str] = []
        self.last_announced_reminders: list[dict[str, object]] = []
        self.last_announced_alarms: list[dict[str, object]] = []
        self.last_announced_calendar_events: list[dict[str, object]] = []
        self.last_announced_timers: list[dict[str, object]] = []
        self.conversation_mode = bool(self.memory.get("conversation_mode", True))
        self.casual_mode = bool(self.memory.get("casual_mode", True))
        self.language = os.environ.get("COSMIC_LANGUAGE", "en").lower()[:2]

    @staticmethod
    def _normalize_phone_number(number: str) -> str:
        return re.sub(r"\D", "", number)

    def human_reply(self, kind: str, default: str = "") -> str:
        if self.language == "hi":
            replies = {
                "unknown": [
                    "समझ नहीं आया, sorry. आप फिर से बोलेंगे?",
                    "थोड़ा clear बोलिए, फिर मैं तुरंत help करता हूँ।",
                    "मैंने ठीक से नहीं पकड़ा। आप चाहें तो दोबारा बोल दें।",
                ],
                "greeting": [
                    "हाँ जी, बताइए।",
                    "ज़रूर, बोलिए।",
                    "जी, मैं सुन रहा हूँ।",
                    "बोलिए, क्या चाहिए?",
                ],
                "done": [
                    "हो गया, easy.",
                    "Done, कुछ और?",
                    "हो गया।",
                    "मैंने कर दिया।",
                ],
                "cancel": [
                    "ठीक है, रद्द कर दिया।",
                    "कोई बात नहीं, मैंने stop कर दिया।",
                    "Done, रद्द हो गया।",
                ],
            }
            pool = replies.get(kind)
            if not pool:
                return default
            return random.choice(pool)

        replies = {
            "unknown": [
                "Oops, I didn’t catch that. Try asking in a simpler way.",
                "Sorry, I missed that. Say it once more and I’ll handle it.",
                "I didn’t get that. Want to try again?",
            ],
            "greeting": [
                "Hey, I’m here.",
                "Yep, go ahead.",
                "Sure, tell me.",
                "I’m listening.",
            ],
            "done": [
                "Done.",
                "All set.",
                "There you go.",
                "Nice, done.",
            ],
            "cancel": [
                "No problem, cancelled.",
                "Okay, I stopped it.",
                "Cancelled.",
            ],
        }
        pool = replies.get(kind)
        if not pool:
            return default
        return random.choice(pool)

    def process_command(self, command: str) -> CosmicResponse:
        normalized = self.normalize_command(command)
        if not normalized:
            return CosmicResponse(message=self.human_reply("unknown"))

        pending_response = self._handle_pending_flow(command, normalized)
        if pending_response is not None:
            return pending_response

        note_search_response = self._handle_note_search_command(command, normalized)
        if note_search_response is not None:
            return note_search_response

        file_search_response = self._handle_file_search_command(command, normalized)
        if file_search_response is not None:
            return file_search_response

        notes_editor_response = self._handle_notes_editor_command(command, normalized)
        if notes_editor_response is not None:
            return notes_editor_response

        if self.pending_action:
            return self._handle_confirmation(normalized)

        if normalized in {"hindi mod","hindi mode", "speak hindi", "language hindi", "set language hindi", "हिंदी बोलो", "हिंदी मोड", "हिन्दी मोड"}:
            self.language = "hi"
            return CosmicResponse(message=self._msg("Hindi mode turned on.", "हिंदी मोड चालू हो गया है।"), language="hi")

        if normalized in {"english mod","english mode", "speak english", "language english", "set language english", "अंग्रेज़ी बोलो", "english मोड"}:
            self.language = "en"
            return CosmicResponse(message=self._msg("English mode turned on.", "अंग्रेज़ी मोड चालू हो गया है।"), language="en")

        if normalized in {"hello", "hi", "hey", "hiya", "good morning", "good afternoon", "good evening", "namaste", "namaskar", "pranam", "kaise ho", "kaise hain", "kya haal hai", "नमस्ते", "नमस्कार", "कैसे हो", "कैसे हैं", "क्या हाल है", "प्रणाम"}:
            return CosmicResponse(message=self._greeting_reply(), language=self.language)

        if normalized in {"exit", "quit", "stop", "goodbye", "bye", "alvida", "phir milenge", "बंद करो", "बंद", "विदा"}:
            return CosmicResponse(message=self._msg("Alright, I’ll be here when you need me.", "ठीक है, जब भी ज़रूरत हो मैं यहाँ हूँ।"), should_exit=True, language=self.language)

        if self._contains_any(normalized, {"time", "samay", "samay batao", "samay बताओ", "वक्त", "waqt", "samay dikhao", "घड़ी", "घड़ी बताओ", "समय", "समय बताओ", "समय दिखाओ"}):
            now = dt.datetime.now().strftime("%I:%M %p")
            return CosmicResponse(message=self._msg(f"It’s {now}.", f"अभी समय {now} है।"), language=self.language)

        if self._contains_any(normalized, {"date", "day", "today", "tarikh", "tarikh batao", "तारीख", "तारीख बताओ", "दिन", "आज का दिन"}):
            today = dt.datetime.now().strftime("%A, %B %d, %Y")
            return CosmicResponse(message=self._msg(f"Today is {today}.", f"आज {today} है।"), language=self.language)

        wiki_response = self._handle_wikipedia(normalized)
        if wiki_response is not None:
            return wiki_response

        system_response = self._handle_system(normalized)
        if system_response is not None:
            return system_response

        input_response = self._handle_input_actions(command, normalized)
        if input_response is not None:
            return input_response

        memory_response = self._handle_memory_command(command, normalized)
        if memory_response is not None:
            return memory_response

        remember_response = self._handle_remember_command(command, normalized)
        if remember_response is not None:
            return remember_response

        reminder_response = self._handle_reminder_command(command, normalized)
        if reminder_response is not None:
            return reminder_response

        briefing_response = self._handle_briefing_command(normalized)
        if briefing_response is not None:
            return briefing_response

        calendar_response = self._handle_calendar_command(command, normalized)
        if calendar_response is not None:
            return calendar_response

        planner_response = self._handle_planner_command(normalized)
        if planner_response is not None:
            return planner_response

        weather_response = self._handle_weather_command(command, normalized)
        if weather_response is not None:
            return weather_response

        alarm_response = self._handle_alarm_command(command, normalized)
        if alarm_response is not None:
            return alarm_response

        screenshot_response = self._handle_screenshot_command(normalized)
        if screenshot_response is not None:
            return screenshot_response

        translation_response = self._handle_translation_command(command, normalized)
        if translation_response is not None:
            return translation_response

        macro_response = self._handle_macro_command(normalized)
        if macro_response is not None:
            return macro_response

        clipboard_response = self._handle_clipboard_command(command, normalized)
        if clipboard_response is not None:
            return clipboard_response

        timer_response = self._handle_timer_command(command, normalized)
        if timer_response is not None:
            return timer_response

        quick_reply_response = self._handle_quick_reply_command(command, normalized)
        if quick_reply_response is not None:
            return quick_reply_response

        incoming_response = self._handle_incoming_message_command(command, normalized)
        if incoming_response is not None:
            return incoming_response

        if self._starts_with_any(normalized, ("search ", "search karo ", "search koro ", "search ", "search this ", "खोज ", "खोजो ", "तलाश करो ", "तलाश ")):
            query = self._strip_any_prefix(normalized, ("search ", "search karo ", "search koro ", "search this ", "खोज ", "खोजो ", "तलाश करो ", "तलाश "))
            if query:
                return CosmicResponse(
                    message=self._msg(f"Sure, I’m searching for {query}.", f"ठीक है, मैं {query} खोज रहा हूँ।"),
                    action="open_url",
                    data={"url": f"https://www.google.com/search?q={quote(query)}"},
                    language=self.language,
                )

        if self._starts_with_any(normalized, ("open ", "open app ", "खोलो ", "खोलें ", "ओपन ", "कुलो ", "kholo ", "kholen ")):
            target = self._strip_any_prefix(normalized, ("open ", "open app ", "खोलो ", "खोलें ", "ओपन ", "कुलो ", "kholo ", "kholen "))
            if target:
                return self._resolve_open_target(target)

        if self._starts_with_any(normalized, ("play ", "चलाओ ", "चलाइए ", "बजाओ ", "सुनाओ ")):
            query = self._strip_any_prefix(normalized, ("play ", "चलाओ ", "चलाइए ", "बजाओ ", "सुनाओ "))
            if query:
                return CosmicResponse(
                    message=self._msg(f"Got it, I’m looking up {query} on YouTube.", f"ठीक है, मैं YouTube पर {query} खोज रहा हूँ।"),
                    action="open_url",
                    data={"url": f"https://www.youtube.com/results?search_query={quote(query)}"},
                    language=self.language,
                )

        if self._starts_with_any(normalized, ("note ", "write note ", "नोट ", "लिखो ", "याद रखो ")):
            note = self._strip_any_prefix(normalized, ("note ", "write note ", "नोट ", "लिखो ", "याद रखो "))
            if note:
                return CosmicResponse(message=self._msg("Saved it for you.", "मैंने इसे सेव कर लिया है।"), action="save_note", data={"note": note}, language=self.language)

        note_search_response = self._handle_note_search_command(command, normalized)
        if note_search_response is not None:
            return note_search_response

        if self._contains_any(normalized, {"joke", "mazaak", "मज़ाक", "मजाक"}):
            return CosmicResponse(message=random.choice(self.jokes()), language=self.language)

        if self._contains_any(normalized, {"help", "help me", "commands", "show commands", "list commands", "all commands", "what can you do", "what do you do", "madad", "help करो", "मदद", "कमांड्स"}):
            return CosmicResponse(message=self.command_guide(), language=self.language)

        if self._contains_any(normalized, {"who are you", "your name", "tum kaun ho", "tumhara naam", "तुम कौन हो", "तुम्हारा नाम", "आप कौन हैं", "आपका नाम"}):
            return CosmicResponse(message=self._msg(f"I’m {self.assistant_name}, your personal assistant.", f"मैं {self.assistant_name} हूँ, आपका personal assistant।"), language=self.language)

        return self.chat_response(command)

    def _greeting_reply(self) -> str:
        hour = dt.datetime.now().hour
        if hour < 12:
            time_greeting = "Good morning"
            hindi_greeting = "सुप्रभात"
        elif hour < 18:
            time_greeting = "Good afternoon"
            hindi_greeting = "नमस्ते"
        else:
            time_greeting = "Good evening"
            hindi_greeting = "शुभ संध्या"

        if self.language == "hi":
            replies = [
                f"{hindi_greeting}। क्या चल रहा है?",
                f"{hindi_greeting}। मैं सुन रहा हूँ।",
                f"नमस्ते। बताइए क्या चाहिए?",
                f"हाँ जी, बोलिए।",
            ]
            return random.choice(replies)

        replies = [
            f"{time_greeting}. What’s up?",
            f"{time_greeting}. I’m listening.",
            f"Hey there. What can I help with?",
            f"Hello. Go ahead.",
        ]
        return random.choice(replies)

    def _msg(self, english: str, hindi: str) -> str:
        return hindi if self.language == "hi" else english

    def _handle_confirmation(self, normalized: str) -> CosmicResponse:
        if normalized in {"yes", "confirm", "do it", "ok", "okay"}:
            action = self.pending_action
            self.pending_action = ""
            messages = {
                "shutdown_system": "Okay, shutting down now.",
                "restart_system": "Alright, restarting now.",
                "sleep_system": "Sure, putting the system to sleep now.",
                "logoff_system": "Okay, logging off now.",
            }
            hindi_messages = {
                "shutdown_system": "ठीक है, अब सिस्टम बंद कर रहा हूँ।",
                "restart_system": "ठीक है, अब सिस्टम रीस्टार्ट कर रहा हूँ।",
                "sleep_system": "ठीक है, अब सिस्टम को स्लीप में भेज रहा हूँ।",
                "logoff_system": "ठीक है, अब लॉग ऑफ कर रहा हूँ।",
            }
            return CosmicResponse(
                message=(hindi_messages if self.language == "hi" else messages).get(action, "Confirmed." if self.language != "hi" else "ठीक है।"),
                should_exit=action in {"shutdown_system", "restart_system", "sleep_system", "logoff_system"},
                action=action,
                language=self.language,
            )

        if normalized in {"no", "cancel", "stop", "never mind", "nevermind"}:
            self.pending_action = ""
            return CosmicResponse(message=self.human_reply("cancel"), language=self.language)

        return CosmicResponse(message=self._msg("Just say yes or no.", "बस हाँ या नहीं बोलिए।"), language=self.language)

    def _handle_pending_flow(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if self.pending_action == "whatsapp_chat":
            response = self._resolve_whatsapp_chat(raw_command.strip())
            if response.action:
                self.pending_action = ""
            else:
                self.pending_contact_name = raw_command.strip()
            return response

        if self.pending_action == "whatsapp_message":
            contact = self.pending_contact_name.strip()
            if not contact:
                self.pending_action = ""
                return CosmicResponse(message="Tell me who the message is for.")
            reply_text = raw_command.strip()
            if self._looks_like_phone_number(reply_text):
                self.pending_contact_number = re.sub(r"\D", "", reply_text)
                if self.pending_message_text:
                    response = self._send_whatsapp_message(
                        contact,
                        self.pending_message_text,
                        number_override=self.pending_contact_number,
                    )
                    if response.action:
                        self.pending_action = ""
                        self.pending_contact_name = ""
                        self.pending_contact_number = ""
                        self.pending_message_text = ""
                    return response
                return CosmicResponse(
                    message=self._msg(
                        f"Got it. Now tell me the message you want to send to {contact}.",
                        f"ठीक है। अब {contact} को भेजने के लिए message बताइए।",
                    )
                )

            if not self.pending_message_text:
                self.pending_message_text = reply_text

            response = self._send_whatsapp_message(
                contact,
                self.pending_message_text,
                number_override=self.pending_contact_number,
            )
            if response.action:
                self.pending_action = ""
                self.pending_contact_name = ""
                self.pending_contact_number = ""
                self.pending_message_text = ""
            return response

        if self.pending_action == "reply_message":
            contact = self.pending_contact_name.strip()
            if not contact:
                self.pending_action = ""
                return CosmicResponse(message="Tell me who sent the message.")

            reply_text = raw_command.strip()
            if self._looks_like_phone_number(reply_text):
                self.pending_contact_number = re.sub(r"\D", "", reply_text)
                if not self.pending_message_text:
                    return CosmicResponse(
                        message=self._msg(
                            f"Got it. Now tell me the message you want to send to {contact}.",
                            f"ठीक है। अब {contact} को भेजने के लिए message बताइए।",
                        )
                    )

            if not self.pending_message_text:
                self.pending_message_text = reply_text

            response = self._send_whatsapp_message(
                contact,
                self.pending_message_text,
                number_override=self.pending_contact_number,
            )
            if response.action:
                self.pending_action = ""
                self.pending_contact_name = ""
                self.pending_contact_number = ""
                self.pending_message_text = ""
            return response

        if self.pending_action == "remember_contact":
            name = self.pending_contact_name.strip()
            number = re.sub(r"\D", "", raw_command)
            if not name:
                self.pending_action = ""
                return CosmicResponse(message="Tell me the contact name again.")
            if len(number) >= 7:
                self._set_contact(name, number)
                self.pending_action = ""
                self.pending_contact_name = ""
                return CosmicResponse(message=f"Saved {name} in contacts.")
            return CosmicResponse(message=f"Tell me the phone number for {name}.")

        return None

    def _handle_wikipedia(self, normalized: str) -> CosmicResponse | None:
        prefixes = ("wikipedia ", "wiki ")
        for prefix in prefixes:
            if normalized.startswith(prefix):
                topic = normalized.removeprefix(prefix).strip()
                return self.wikipedia_lookup(topic)
        return None

    def wikipedia_lookup(self, topic: str) -> CosmicResponse:
        if not topic:
            return CosmicResponse(message="Tell me what topic you want me to search on Wikipedia.")

        if wikipedia is None:
            return CosmicResponse(message="Wikipedia support is not installed yet. Please add the wikipedia package.")

        try:
            summary = wikipedia.summary(topic, sentences=2, auto_suggest=True, redirect=True)
            return CosmicResponse(message=summary)
        except wikipedia.DisambiguationError as exc:  # type: ignore[attr-defined]
            options = ", ".join(exc.options[:5])
            return CosmicResponse(message=f"That one is a bit broad. Try one of these: {options}.")
        except wikipedia.PageError:  # type: ignore[attr-defined]
            return CosmicResponse(message=f"I could not find a Wikipedia page for {topic}.")
        except Exception:
            logger.exception("Wikipedia lookup failed for topic=%r", topic)
            return CosmicResponse(message=f"I couldn’t fetch Wikipedia results for {topic}.")

    def chat_response(self, user_text: str) -> CosmicResponse:
        text = user_text.lower().strip()

        if any(phrase in text for phrase in {"what is my name", "who am i", "do you know my name", "my name"}):
            profile = self.memory.get("profile", {})
            if isinstance(profile, dict):
                preferred = str(profile.get("preferred name", "")).strip() or str(profile.get("name", "")).strip()
                if preferred:
                    return CosmicResponse(message=self._msg(f"Your name is {preferred}.", f"आपका नाम {preferred} है।"), language=self.language)
            return CosmicResponse(message=self._msg("I do not know your name yet. You can tell me by saying: my name is ...", "मुझे अभी आपका नाम नहीं पता। आप बोल सकते हैं: my name is ..."), language=self.language)

        if "how are you" in text:
            return CosmicResponse(message=self._msg("I’m doing well, thanks for asking.", "मैं अच्छा हूँ, पूछने के लिए धन्यवाद।"), language=self.language)

        if "what can you do" in text:
            return CosmicResponse(
                message=self._msg(
                    "I can tell the time and date, search Wikipedia, open apps and websites, type text, press keys, call contacts or numbers, save notes, and handle system actions.",
                    "मैं समय और तारीख बता सकता हूँ, Wikipedia देख सकता हूँ, ऐप और वेबसाइट खोल सकता हूँ, टेक्स्ट टाइप कर सकता हूँ, कीबोर्ड चल सकता हूँ, कॉल कर सकता हूँ, नोट सेव कर सकता हूँ, और सिस्टम कमांड कर सकता हूँ।",
                ),
                language=self.language,
            )

        if "thank you" in text or "thanks" in text:
            return CosmicResponse(message=self._msg("You’re welcome.", "आपका स्वागत है।"), language=self.language)

        if "who made you" in text or "who create you" in text:
            return CosmicResponse(message=self._msg("I was built by Aniket Mandawariya as a personal assistant named Cosmic.", "मुझे Aniket Mandawariya ने personal assistant के रूप में बनाया गया है।"), language=self.language)

        if "what is your name" in text or "your name" in text:
            return CosmicResponse(message=self._msg(f"My name is {self.assistant_name}.", f"मेरा नाम {self.assistant_name} है।"), language=self.language)
        if self.conversation_mode and any(phrase in text for phrase in {"how are you doing", "what's up", "whats up", "how is it going"}):
            profile = self.memory.get("profile", {})
            name = ""
            if isinstance(profile, dict):
                name = str(profile.get("preferred name", "")).strip() or str(profile.get("name", "")).strip()
            if name:
                return CosmicResponse(message=self._msg(f"I’m good, {name}. What about you?", f"मैं ठीक हूँ, {name}। आप कैसे हैं?"), language=self.language)
            return CosmicResponse(message=self._msg("I’m good. What about you?", "मैं ठीक हूँ। आप कैसे हैं?"), language=self.language)

        return CosmicResponse(
            message=self._msg(
                "I'm in local mode right now. I can still help with time, dates, Wikipedia, web searches, opening apps, YouTube, notes, notes editor, file search, clipboard manager, focus mode, typing text, keyboard shortcuts, calling, and system actions.",
                "मैं अभी लोकल मोड में हूँ। फिर भी मैं समय, तारीख, Wikipedia, वेब खोज, ऐप खोलना, YouTube, notes editor, file search, clipboard manager, focus mode, टेक्स्ट टाइप करना, कीबोर्ड शॉर्टकट, कॉल और सिस्टम कमांड में मदद कर सकता हूँ।",
            ),
            language=self.language,
        )

    def _handle_system(self, normalized: str) -> CosmicResponse | None:
        if normalized in {"lock", "lock pc", "lock system"}:
            return CosmicResponse(message="Locking the system now.", action="lock_system")

        if normalized in {"sleep", "sleep pc", "sleep system"}:
            self.pending_action = "sleep_system"
            return CosmicResponse(
                message="Want me to put the system to sleep? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"restart", "restart pc", "reboot"}:
            self.pending_action = "restart_system"
            return CosmicResponse(
                message="Want me to restart the system? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"shutdown", "shut down", "power off"}:
            self.pending_action = "shutdown_system"
            return CosmicResponse(
                message="Want me to shut down the system? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"log off", "logoff", "sign out"}:
            self.pending_action = "logoff_system"
            return CosmicResponse(
                message="Want me to log off the current user? Say yes to confirm or no to cancel.",
                needs_confirmation=True,
            )

        if normalized in {"minimize all", "show desktop", "desktop"}:
            return CosmicResponse(message="Sure, showing the desktop.", action="show_desktop")

        if normalized in {"task manager", "open task manager"}:
            return CosmicResponse(message="Sure, opening Task Manager.", action="open_app", data={"app_name": "taskmgr.exe"})

        if normalized in {"volume up", "louder"}:
            return CosmicResponse(message="Turning the volume up.", action="adjust_volume", data={"direction": "up"})

        if normalized in {"volume down", "lower volume"}:
            return CosmicResponse(message="Turning the volume down.", action="adjust_volume", data={"direction": "down"})

        if normalized in {"mute", "unmute"}:
            return CosmicResponse(message="Toggling mute.", action="adjust_volume", data={"direction": "mute"})

        volume_set = self._extract_level_command(
            normalized,
            prefixes=("set volume ", "volume to ", "volume ", "audio level ", "sound level ", "वॉल्यूम ", "आवाज़ ", "आवाज ", "आवाज़ "),
            keywords={"volume", "sound", "audio", "awaz", "aawaz", "aawaaz", "avaaz", "वॉल्यूम", "आवाज", "आवाज़"},
            action="set_volume",
            message_label="volume",
        )
        if volume_set is not None:
            return volume_set

        if normalized in {"brightness up", "brighter", "increase brightness"}:
            return CosmicResponse(message="Turning the brightness up.", action="adjust_brightness", data={"direction": "up"})

        if normalized in {"brightness down", "dim screen", "decrease brightness"}:
            return CosmicResponse(message="Turning the brightness down.", action="adjust_brightness", data={"direction": "down"})

        brightness_set = self._extract_level_command(
            normalized,
            prefixes=("set brightness ", "brightness to ", "brightness ", "screen brightness ", "ब्राइटनेस ", "चमक ", "रोशनी "),
            keywords={"brightness", "light", "chamak", "roshni", "ब्राइटनेस", "चमक", "रोशनी"},
            action="set_brightness",
            message_label="brightness",
        )
        if brightness_set is not None:
            return brightness_set

        if normalized.startswith("close "):
            target = normalized.removeprefix("close ").strip()
            if target in {"window", "app", "application"}:
                return CosmicResponse(message="Closing the active window.", action="close_active_window")
            if target:
                return CosmicResponse(message=f"Closing {target}.", action="close_process", data={"name": target})

        return None

    def _handle_input_actions(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized.startswith(("paste clipboard", "paste history", "paste copied", "paste item")):
            return None

        type_prefixes = ("type message ", "type ", "write ", "paste ", "टाइप ", "लिखो ", "पेस्ट ", "type करो ")
        for prefix in type_prefixes:
            if normalized.startswith(prefix):
                text = self._raw_argument(raw_command, prefix)
                if not text:
                    return CosmicResponse(message=self._msg("Tell me what text you want me to type.", "बताइए क्या टाइप करना है।"))
                return CosmicResponse(message=f"Typing {text}.", action="type_text", data={"text": text})

        if self._starts_with_any(normalized, ("press ", "दबाओ ", "प्रेस ", "दबाइए ")):
            keys_text = self._strip_any_prefix(normalized, ("press ", "दबाओ ", "प्रेस ", "दबाइए "))
            return self._build_key_action(keys_text, "Pressing")

        if self._starts_with_any(normalized, ("hotkey ", "कीबोर्ड शॉर्टकट ", "शॉर्टकट ", "shortcut ")):
            keys_text = self._strip_any_prefix(normalized, ("hotkey ", "कीबोर्ड शॉर्टकट ", "शॉर्टकट ", "shortcut "))
            return self._build_key_action(keys_text, "Using")

        if self._starts_with_any(normalized, ("scroll faster", "fast scroll", "scroll quicker", "scroll more")):
            direction = "up" if "up" in normalized else "down"
            amount = 20
            page_label = "the current page"
            return CosmicResponse(
                message=self._msg(
                    f"Scrolling {page_label} faster {direction}.",
                    f"{page_label} ko aur tez {direction} ki taraf scroll kar raha hoon.",
                ),
                action="scroll_page",
                data={"direction": direction, "amount": str(amount)},
                language=self.language,
            )

        if self._starts_with_any(normalized, ("scroll slower", "slow scroll", "scroll less")):
            direction = "up" if "up" in normalized else "down"
            amount = 5
            page_label = "the current page"
            return CosmicResponse(
                message=self._msg(
                    f"Scrolling {page_label} slower {direction}.",
                    f"{page_label} ko dheere {direction} ki taraf scroll kar raha hoon.",
                ),
                action="scroll_page",
                data={"direction": direction, "amount": str(amount)},
                language=self.language,
            )

        if self._starts_with_any(normalized, ("scroll a little", "scroll little", "scroll slightly", "scroll small")):
            direction = "up" if "up" in normalized else "down"
            amount = 5
            page_label = "the current page"
            return CosmicResponse(
                message=self._msg(
                    f"Scrolling {page_label} a little {direction}.",
                    f"{page_label} ko thoda sa {direction} ki taraf scroll kar raha hoon.",
                ),
                action="scroll_page",
                data={"direction": direction, "amount": str(amount)},
                language=self.language,
            )

        if self._starts_with_any(normalized, ("scroll a lot", "scroll alot", "scroll a bunch", "scroll heavily")):
            direction = "up" if "up" in normalized else "down"
            amount = 20
            page_label = "the current page"
            return CosmicResponse(
                message=self._msg(
                    f"Scrolling {page_label} a lot {direction}.",
                    f"{page_label} ko kaafi zyada {direction} ki taraf scroll kar raha hoon.",
                ),
                action="scroll_page",
                data={"direction": direction, "amount": str(amount)},
                language=self.language,
            )

        if self._starts_with_any(
            normalized,
            (
                "scroll current page",
                "scroll this page",
                "scroll active page",
                "scroll active tab",
                "scroll browser page",
                "scroll youtube page",
                "scroll page",
                "scroll ",
                "page ",
                "scroll up",
                "scroll down",
                "page up",
                "page down",
            ),
        ):
            direction = "up" if "up" in normalized else "down" if "down" in normalized else "down"
            amount_match = re.search(r"\b(\d+)\b", normalized)
            amount = int(amount_match.group(1)) if amount_match else 8
            if "youtube" in normalized:
                page_label = "the YouTube page"
            elif "tab" in normalized:
                page_label = "the active tab"
            elif "browser" in normalized:
                page_label = "the browser page"
            elif "page" in normalized:
                page_label = "the current page"
            else:
                page_label = "the page"
            return CosmicResponse(message=self._msg(f"Scrolling {page_label} {direction}.", f"{page_label} ko {direction} ki taraf scroll kar raha hoon."), action="scroll_page", data={"direction": direction, "amount": str(amount)}, language=self.language)

        mouse_click_commands = {
            "click": ("left", 1),
            "left click": ("left", 1),
            "double click": ("left", 2),
            "right click": ("right", 1),
            "middle click": ("middle", 1),
        }
        if normalized in mouse_click_commands:
            button, count = mouse_click_commands[normalized]
            label = "double clicking" if count == 2 else f"{button} clicking"
            return CosmicResponse(message=self._msg(f"{label.capitalize()}.", f"{label.capitalize()} kar raha hoon."), action="mouse_click", data={"button": button, "clicks": str(count)}, language=self.language)

        mouse_move_match = re.match(r"^(?:move mouse|mouse move|move cursor|cursor move|mouse)\s+(?:(?P<amount>\d+)\s+)?(?P<direction>up|down|left|right)(?:\s+(?P<amount2>\d+))?$", normalized)
        if mouse_move_match:
            amount_text = mouse_move_match.group("amount") or mouse_move_match.group("amount2") or "100"
            direction = mouse_move_match.group("direction")
            return CosmicResponse(message=self._msg(f"Moving the mouse {direction}.", f"Mouse ko {direction} ki taraf le ja raha hoon."), action="move_mouse", data={"direction": direction, "amount": str(amount_text)}, language=self.language)

        whatsapp_message = self._handle_whatsapp_message_command(raw_command, normalized)
        if whatsapp_message is not None:
            return whatsapp_message

        for prefix in ("call ", "dial ", "कॉल ", "फोन करो ", "फोन लगाओ ", "डायल "):
            if normalized.startswith(prefix):
                target = self._raw_argument(raw_command, prefix)
                return self._resolve_call_target(target)

        return None

    def _handle_remember_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if not self._starts_with_any(normalized, ("remember ", "याद रखो ", "याद करो ", "सेव करो ", "save ")):
            return None

        raw_text = re.sub(r"[^\w\s+]", "", raw_command.strip())
        match = re.match(
            r"^(?:remember|याद रखो|याद करो|सेव करो|save)(?: this is)?(?: my)? (?P<name>.+?) mobile (?:no|number|नंबर|नं)(?: is)?(?: (?P<number>.+))?$",
            raw_text,
            flags=re.IGNORECASE,
        )
        if not match:
            return CosmicResponse(
                message=self._msg("Tell me it like: remember this is my maa mobile no 9876543210.", "ऐसे बोलें: remember this is my maa mobile no 9876543210.")
            )

        name = match.group("name").strip()
        number_text = (match.group("number") or "").strip()
        number = re.sub(r"\D", "", number_text)

        if name.lower().startswith("my "):
            name = name[3:].strip()

        if number and len(number) >= 7:
            self._set_contact(name, number)
            return CosmicResponse(message=self._msg(f"Saved {name} in contacts.", f"{name} contacts में सेव हो गया।"))

        self.pending_action = "remember_contact"
        self.pending_contact_name = name
        return CosmicResponse(message=self._msg(f"Tell me the phone number for {name}.", f"{name} का फोन नंबर बताइए।"))

    def _handle_memory_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"what do you remember", "what do you know about me", "show memory", "list memory", "memory"}:
            return CosmicResponse(message=self.memory_summary(), language=self.language)

        if normalized in {"forget memory", "clear memory", "reset memory", "forget everything"}:
            self.forget_memory()
            return CosmicResponse(message=self._msg("I cleared what I remembered.", "मैंने आपकी memory साफ कर दी है।"), language=self.language)

        if normalized in {"chat mode", "conversation mode", "natural mode", "talk mode"}:
            self.conversation_mode = True
            self.memory["conversation_mode"] = True
            self._save_memory(self.memory)
            return CosmicResponse(message=self._msg("Conversation mode is on. I will reply more naturally now.", "Conversation mode चालू है। अब मैं ज़्यादा natural तरीके से reply करूँगा।"), language=self.language)

        if normalized in {"command mode", "assistant mode", "strict mode"}:
            self.conversation_mode = False
            self.memory["conversation_mode"] = False
            self._save_memory(self.memory)
            return CosmicResponse(message=self._msg("Command mode is on.", "Command mode चालू है।"), language=self.language)

        if normalized in {"casual mode", "friendly mode", "human mode", "relaxed mode"}:
            self.casual_mode = True
            self.memory["casual_mode"] = True
            self._save_memory(self.memory)
            return CosmicResponse(message=self._msg("Casual mode is on. I’ll sound more natural now.", "Casual mode चालू है। अब मैं ज़्यादा natural लगूँगा।"), language=self.language)

        if normalized in {"formal mode", "robot mode", "strict replies", "professional mode"}:
            self.casual_mode = False
            self.memory["casual_mode"] = False
            self._save_memory(self.memory)
            return CosmicResponse(message=self._msg("Formal mode is on.", "Formal mode चालू है।"), language=self.language)

        remember_match = re.match(
            r"^(?:remember that|remember|save that|note that)\s+(?P<fact>.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if remember_match:
            fact = remember_match.group("fact").strip()
            if not fact:
                return CosmicResponse(message=self._msg("Tell me what to remember.", "बताइए क्या याद रखना है।"), language=self.language)
            self._store_memory_fact(fact)
            return CosmicResponse(message=self._msg("I will remember that.", "मैं यह याद रखूँगा।"), language=self.language)

        if normalized.startswith("my name is "):
            name = normalized.removeprefix("my name is ").strip()
            if name:
                self._store_memory_fact(f"my name is {name}")
                return CosmicResponse(message=self._msg(f"Nice to meet you, {name}. I’ll remember your name.", f"नमस्ते {name}। मैं आपका नाम याद रखूँगा।"), language=self.language)

        if normalized.startswith("call me "):
            name = normalized.removeprefix("call me ").strip()
            if name:
                self._store_memory_fact(f"my preferred name is {name}")
                return CosmicResponse(message=self._msg(f"Okay, I’ll call you {name}.", f"ठीक है, मैं आपको {name} कहूँगा।"), language=self.language)

        return None

    def _handle_reminder_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"list reminders", "show reminders", "reminders", "my reminders"}:
            return CosmicResponse(message=self.list_reminders(), language=self.language)

        cancel_match = re.match(r"^(?:cancel reminder|remove reminder|delete reminder)\s*(?P<index>\d+)?$", normalized)
        if cancel_match:
            index_text = cancel_match.group("index")
            if not index_text:
                return CosmicResponse(message=self._msg("Tell me which reminder number to cancel.", "बताइए कौन सा reminder cancel करना है।"), language=self.language)
            removed = self.cancel_reminder(int(index_text))
            if removed:
                return CosmicResponse(message=self._msg(f"I cancelled reminder {index_text}.", f"मैंने reminder {index_text} cancel कर दिया है।"), language=self.language)
            return CosmicResponse(message=self._msg("I could not find that reminder.", "मुझे वह reminder नहीं मिला।"), language=self.language)

        snooze_match = re.match(
            r"^(?:snooze reminder|snooze)\s*(?P<target>last|\d+|it|this)?(?:\s+for\s+(?P<when>.+))?$",
            normalized,
            flags=re.IGNORECASE,
        )
        if snooze_match:
            target = (snooze_match.group("target") or "").strip().lower()
            when_text = (snooze_match.group("when") or "").strip() or "10 minutes"
            new_when = self._parse_snooze_time(when_text)
            if new_when is None:
                return CosmicResponse(
                    message=self._msg(
                        "Try saying: snooze reminder 1 for 10 minutes, or snooze last reminder for 15 minutes.",
                        "aise bolen: snooze reminder 1 for 10 minutes, ya snooze last reminder for 15 minutes.",
                    ),
                    language=self.language,
                )

            reminder = self._find_reminder_for_snooze(target)
            if reminder is None:
                return CosmicResponse(message=self._msg("I could not find a reminder to snooze.", "mujhe snooze karne ke liye reminder nahi mila."), language=self.language)

            reminder["done"] = True
            snoozed_text = str(reminder.get("text", "")).strip()
            if not snoozed_text:
                return CosmicResponse(message=self._msg("I could not snooze that reminder.", "main us reminder ko snooze nahi kar saka."), language=self.language)

            self.add_reminder(new_when, snoozed_text)
            self._save_reminders(self.reminders)
            return CosmicResponse(
                message=self._msg(
                    f"Okay, I snoozed it until {new_when.strftime('%I:%M %p on %B %d')}.",
                    f"theek hai, maine use {new_when.strftime('%d %B %I:%M %p')} tak snooze kar diya.",
                ),
                language=self.language,
            )

        reminder_match = re.match(
            r"^(?:remind me|set reminder|reminder)\s+(?P<when>.+?)\s+(?:to|about)\s+(?P<task>.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if not reminder_match:
            return None

        when_text = reminder_match.group("when").strip()
        task = reminder_match.group("task").strip()
        when = self._parse_reminder_time(when_text)
        if when is None or not task:
            return CosmicResponse(
                message=self._msg(
                    "Try saying: remind me in 10 minutes to drink water, or remind me at 5 pm to call mom.",
                    "ऐसे बोलें: remind me in 10 minutes to drink water, या remind me at 5 pm to call mom.",
                ),
                language=self.language,
            )

        reminder_id = self.add_reminder(when, task)
        return CosmicResponse(
            message=self._msg(
                f"Okay, I’ll remind you to {task} at {when.strftime('%I:%M %p on %B %d')}.",
                f"ठीक है, मैं आपको {task} के लिए {when.strftime('%d %B %I:%M %p')} पर याद दिलाऊँगा।",
            ),
            language=self.language,
            data={"reminder_id": reminder_id},
        )

    def _store_memory_fact(self, fact: str) -> None:
        text = fact.strip()
        if not text:
            return

        self.remember_fact("fact", text)
        name_match = re.match(r"^my name is (?P<name>.+)$", text, flags=re.IGNORECASE)
        if name_match:
            self.remember_fact("name", name_match.group("name").strip())
            return

        preferred_match = re.match(r"^my preferred name is (?P<name>.+)$", text, flags=re.IGNORECASE)
        if preferred_match:
            self.remember_fact("preferred name", preferred_match.group("name").strip())
            return

    @staticmethod
    def _parse_reminder_time(when_text: str) -> dt.datetime | None:
        text = when_text.lower().strip()
        now = dt.datetime.now()

        in_match = re.match(r"^in\s+(?P<num>\d+)\s*(?P<unit>seconds?|minutes?|hours?)$", text)
        if in_match:
            amount = int(in_match.group("num"))
            unit = in_match.group("unit")
            if unit.startswith("second"):
                return now + dt.timedelta(seconds=amount)
            if unit.startswith("minute"):
                return now + dt.timedelta(minutes=amount)
            if unit.startswith("hour"):
                return now + dt.timedelta(hours=amount)

        at_match = re.match(r"^at\s+(?P<time>.+)$", text)
        if at_match:
            time_text = at_match.group("time").strip()
            for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H"):
                try:
                    parsed = dt.datetime.strptime(time_text, fmt).time()
                    candidate = dt.datetime.combine(now.date(), parsed)
                    if candidate < now:
                        candidate += dt.timedelta(days=1)
                    return candidate
                except Exception:
                    continue

        tomorrow_match = re.match(r"^tomorrow at (?P<time>.+)$", text)
        if tomorrow_match:
            time_text = tomorrow_match.group("time").strip()
            for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H"):
                try:
                    parsed = dt.datetime.strptime(time_text, fmt).time()
                    return dt.datetime.combine(now.date() + dt.timedelta(days=1), parsed)
                except Exception:
                    continue

        return None

    @classmethod
    def _load_alarms(cls) -> list[dict[str, object]]:
        path = cls._alarms_file()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load alarms from %s", path)
            return []
        if not isinstance(payload, list):
            return []
        alarms: list[dict[str, object]] = []
        for item in payload:
            if isinstance(item, dict):
                alarms.append(item)
        return alarms

    @classmethod
    def _save_alarms(cls, alarms: list[dict[str, object]]) -> None:
        try:
            with open(cls._alarms_file(), "w", encoding="utf-8") as file:
                json.dump(alarms, file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save alarms")

    @staticmethod
    def _alarms_file() -> str:
        return os.path.join(os.path.dirname(__file__), "cosmic_alarms.json")

    def add_alarm(self, when: dt.datetime, text: str) -> str:
        alarm = {
            "id": random.randint(100000, 999999),
            "when": when.isoformat(timespec="seconds"),
            "text": text.strip(),
            "done": False,
        }
        self.alarms.append(alarm)
        self._save_alarms(self.alarms)
        return str(alarm["id"])

    def list_alarms(self) -> str:
        active = [item for item in self.alarms if not item.get("done")]
        if not active:
            return self._msg("You do not have any alarms.", "aapke paas koi alarm nahi hai.")
        lines = []
        for idx, item in enumerate(active, start=1):
            when_text = str(item.get("when", ""))
            text = str(item.get("text", ""))
            lines.append(f"{idx}. {text} at {when_text}")
        return self._msg("Your alarms are: " + "; ".join(lines), "aapke alarms hain: " + "; ".join(lines))

    def cancel_alarm(self, index: int) -> str:
        active = [item for item in self.alarms if not item.get("done")]
        if index < 1 or index > len(active):
            return ""
        target = active[index - 1]
        target["done"] = True
        self._save_alarms(self.alarms)
        return str(target.get("text", ""))

    def pop_due_alarms(self) -> list[str]:
        now = dt.datetime.now()
        announcements: list[str] = []
        changed = False
        self.last_announced_alarms = []
        for item in self.alarms:
            if item.get("done"):
                continue
            when_text = str(item.get("when", ""))
            try:
                due_at = dt.datetime.fromisoformat(when_text)
            except Exception:
                continue
            if due_at <= now:
                item["done"] = True
                changed = True
                text = str(item.get("text", "")).strip()
                if text:
                    announcements.append(self._msg(f"Alarm: {text}.", f"alarm: {text}."))
                    self.last_announced_alarms.append({"id": item.get("id"), "text": text, "when": when_text})
        if changed:
            self._save_alarms(self.alarms)
        return announcements

    def _fetch_weather_summary(self, location: str = "") -> str:
        place = location.strip()
        url = f"https://wttr.in/{quote(place)}?format=j1" if place else "https://wttr.in/?format=j1"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            if place:
                return self._msg(f"I could not fetch weather for {place} right now.", f"main abhi {place} ka weather nahi la pa raha hoon.")
            return self._msg("I could not fetch the weather right now.", "main abhi weather nahi la pa raha hoon.")

        current = (payload.get("current_condition") or [{}])[0]
        area = ((payload.get("nearest_area") or [{}])[0].get("areaName") or [{}])[0].get("value", place or "your area")
        temp_c = current.get("temp_C", "?")
        feels_like = current.get("FeelsLikeC", temp_c)
        desc_list = current.get("weatherDesc") or [{}]
        description = desc_list[0].get("value", "weather") if isinstance(desc_list, list) and desc_list else "weather"
        humidity = current.get("humidity", "?")
        return self._msg(
            f"Weather for {area}: {description}, {temp_c}?C, feels like {feels_like}?C, humidity {humidity}%.",
            f"{area} ka weather: {description}, {temp_c} degree, mehsoos {feels_like} degree, humidity {humidity} pratishat.",
        )

    def _translate_text(self, text: str, target_lang: str) -> str:
        source_lang = "hi" if re.search(r"[ऀ-ॿ]", text) else "en"
        if source_lang == target_lang:
            return text

        local = self._local_translate(text, source_lang, target_lang)
        if local:
            return local

        pair = f"{source_lang}|{target_lang}"
        url = f"https://api.mymemory.translated.net/get?q={quote(text)}&langpair={pair}"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = ((payload.get("responseData") or {}).get("translatedText") or "").strip()
            return translated or text
        except Exception:
            return ""

    @staticmethod
    def _local_translate(text: str, source_lang: str, target_lang: str) -> str:
        phrase_maps = {
            ("en", "hi"): {
                "hello": "नमस्ते",
                "hi": "नमस्ते",
                "good morning": "सुप्रभात",
                "good afternoon": "शुभ दोपहर",
                "good evening": "शुभ संध्या",
                "good night": "शुभ रात्रि",
                "thank you": "धन्यवाद",
                "thanks": "धन्यवाद",
                "how are you": "आप कैसे हैं",
                "what is your name": "आपका नाम क्या है",
                "my name is": "मेरा नाम है",
                "weather": "मौसम",
                "alarm": "अलार्म",
                "screenshot": "स्क्रीनशॉट",
                "translate": "अनुवाद",
                "yes": "हाँ",
                "no": "नहीं",
            },
            ("hi", "en"): {
                "नमस्ते": "hello",
                "सुप्रभात": "good morning",
                "शुभ दोपहर": "good afternoon",
                "शुभ संध्या": "good evening",
                "शुभ रात्रि": "good night",
                "धन्यवाद": "thank you",
                "आप कैसे हैं": "how are you",
                "आपका नाम क्या है": "what is your name",
                "मेरा नाम है": "my name is",
                "मौसम": "weather",
                "अलार्म": "alarm",
                "स्क्रीनशॉट": "screenshot",
                "अनुवाद": "translate",
                "हाँ": "yes",
                "नहीं": "no",
            },
        }
        word_maps = {
            ("en", "hi"): {
                "hello": "नमस्ते",
                "hi": "नमस्ते",
                "weather": "मौसम",
                "alarm": "अलार्म",
                "screenshot": "स्क्रीनशॉट",
                "translate": "अनुवाद",
                "please": "कृपया",
                "open": "खोलो",
                "close": "बंद करो",
                "show": "दिखाओ",
                "what": "क्या",
                "is": "है",
                "my": "मेरा",
                "name": "नाम",
                "you": "आप",
                "are": "हैं",
                "how": "कैसे",
                "thanks": "धन्यवाद",
                "thank": "धन्यवाद",
                "yes": "हाँ",
                "no": "नहीं",
            },
            ("hi", "en"): {
                "नमस्ते": "hello",
                "मौसम": "weather",
                "अलार्म": "alarm",
                "स्क्रीनशॉट": "screenshot",
                "अनुवाद": "translate",
                "कृपया": "please",
                "खोलो": "open",
                "बंद": "close",
                "दिखाओ": "show",
                "क्या": "what",
                "है": "is",
                "मेरा": "my",
                "नाम": "name",
                "आप": "you",
                "हैं": "are",
                "कैसे": "how",
                "धन्यवाद": "thank you",
                "हाँ": "yes",
                "नहीं": "no",
            },
        }

        cleaned = text.strip().lower()
        cleaned = re.sub(r"[^\w\sऀ-ॿ]", "", cleaned)
        phrase_map = phrase_maps.get((source_lang, target_lang), {})
        for phrase in sorted(phrase_map, key=len, reverse=True):
            if cleaned == phrase or cleaned.startswith(phrase + " "):
                replacement = phrase_map[phrase]
                remainder = cleaned[len(phrase):].strip()
                return (replacement + (" " + remainder if remainder else "")).strip()

        words = cleaned.split()
        if not words:
            return ""
        word_map = word_maps.get((source_lang, target_lang), {})
        mapped = [word_map.get(word, word) for word in words]
        result = " ".join(mapped).strip()
        return result if result and result != cleaned else ""

    @staticmethod
    def _parse_snooze_time(when_text: str) -> dt.datetime | None:
        text = when_text.lower().strip()
        if not text:
            return None

        now = dt.datetime.now()
        duration_match = re.match(r"^(?:in\s+)?(?P<num>\d+)\s*(?P<unit>seconds?|minutes?|hours?)$", text)
        if duration_match:
            amount = int(duration_match.group("num"))
            unit = duration_match.group("unit")
            if unit.startswith("second"):
                return now + dt.timedelta(seconds=amount)
            if unit.startswith("minute"):
                return now + dt.timedelta(minutes=amount)
            if unit.startswith("hour"):
                return now + dt.timedelta(hours=amount)

        parsed = CosmicEngine._parse_reminder_time(f"in {text}")
        if parsed is not None:
            return parsed

        return None

    def _handle_briefing_command(self, normalized: str) -> CosmicResponse | None:
        if normalized not in {"daily briefing", "brief me", "briefing", "morning briefing", "evening briefing", "today briefing", "daily update"}:
            return None

        now = dt.datetime.now()
        time_text = now.strftime("%I:%M %p")
        date_text = now.strftime("%A, %B %d, %Y")
        due_announcements = (
            self.pop_due_reminders()
            + self.pop_due_alarms()
            + self.pop_due_calendar_events()
            + self.pop_due_timers()
        )
        reminders = [item for item in self.reminders if not item.get("done")]
        calendar_events = [item for item in self.calendar_events if not item.get("done")]
        timers = [item for item in self.timers if not item.get("done")]
        lines: list[str] = []
        weather_summary = self._fetch_weather_summary("")
        if weather_summary and not weather_summary.lower().startswith(("i could not fetch", "main abhi")):
            lines.append(weather_summary)
        if reminders:
            for item in reminders[:3]:
                when_text = str(item.get("when", ""))
                task = str(item.get("text", "")).strip()
                if task:
                    lines.append(f"{task} at {self._format_datetime(when_text)}")
        else:
            lines.append(self._msg("You do not have any active reminders.", "???? ??? active reminders ???? ????"))

        if calendar_events:
            for item in calendar_events[:3]:
                when_text = str(item.get("when", ""))
                title = str(item.get("title", "")).strip()
                if title:
                    lines.append(f"Calendar: {title} at {self._format_datetime(when_text)}")
        else:
            lines.append(self._msg("You do not have any calendar events.", "???? ??? calendar events ???? ????"))

        if timers:
            for item in timers[:3]:
                when_text = str(item.get("when", ""))
                label = str(item.get("text", "")).strip()
                if label:
                    lines.append(f"Timer: {label} at {self._format_datetime(when_text)}")
        else:
            lines.append(self._msg("You do not have any active timers.", "???? ??? active timers ???? ????"))

        summary = self._msg(
            f"Here is your briefing. It is {time_text} on {date_text}. You have {len(reminders)} active reminders, {len(calendar_events)} calendar events, and {len(timers)} active timers.",
            f"?? ???? briefing ??? ??? {date_text} {time_text} ???? ???? {len(reminders)} active reminders, {len(calendar_events)} calendar events, ??? {len(timers)} active timers ????",
        )
        return CosmicResponse(message=summary + " " + self._msg("Upcoming: ", "??? ????: ") + "; ".join(lines), announcements=due_announcements, language=self.language)

    def _handle_calendar_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"calendar", "my calendar", "calendar events", "list events", "show events", "upcoming events", "events"}:
            return CosmicResponse(message=self.list_calendar_events(), language=self.language)

        cancel_match = re.match(r"^(?:cancel event|remove event|delete event)\s*(?P<index>\d+)?$", normalized)
        if cancel_match:
            index_text = cancel_match.group("index")
            if not index_text:
                return CosmicResponse(message=self._msg("Tell me which event number to cancel.", "bataiye kaun sa event cancel karna hai."), language=self.language)
            removed = self.cancel_calendar_event(int(index_text))
            if removed:
                return CosmicResponse(message=self._msg(f"I cancelled event {index_text}.", f"maine event {index_text} cancel kar diya."), language=self.language)
            return CosmicResponse(message=self._msg("I could not find that event.", "mujhe woh event nahi mila."), language=self.language)

        prefixes = (
            "add calendar event ",
            "add event ",
            "create calendar event ",
            "create event ",
            "schedule calendar event ",
            "schedule event ",
            "schedule ",
            "calendar event ",
        )
        details = ""
        for prefix in prefixes:
            if normalized.startswith(prefix):
                details = self._raw_argument(raw_command, prefix)
                break
        if not details:
            return None

        split = self._split_calendar_event_details(details)
        if split is None:
            return CosmicResponse(
                message=self._msg(
                    "Try saying: add event tomorrow at 5 pm team meeting, or schedule team meeting tomorrow at 5 pm.",
                    "aise bolen: add event tomorrow at 5 pm team meeting, ya schedule team meeting tomorrow at 5 pm.",
                ),
                language=self.language,
            )

        when_text, title = split
        when = self._parse_reminder_time(when_text)
        if when is None or not title:
            return CosmicResponse(
                message=self._msg(
                    "Try saying: add event tomorrow at 5 pm team meeting, or schedule team meeting tomorrow at 5 pm.",
                    "aise bolen: add event tomorrow at 5 pm team meeting, ya schedule team meeting tomorrow at 5 pm.",
                ),
                language=self.language,
            )

        event_id = self.add_calendar_event(when, title)
        return CosmicResponse(
            message=self._msg(
                f"Okay, I added {title} to your calendar for {when.strftime('%I:%M %p on %B %d')}.",
                f"theek hai, maine {title} ko aapke calendar me {when.strftime('%d %B %I:%M %p')} ke liye add kar diya.",
            ),
            language=self.language,
            data={"event_id": event_id},
        )

    def _handle_weather_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        keywords = {"weather", "forecast", "temperature", "temp", "rain", "humidity"}
        if not any(word in normalized for word in keywords):
            return None

        location = ""
        for prefix in ("weather in ", "weather at ", "weather for ", "forecast in ", "forecast for ", "temperature in ", "temp in "):
            if normalized.startswith(prefix):
                location = self._raw_argument(raw_command, prefix)
                break

        summary = self._fetch_weather_summary(location)
        return CosmicResponse(message=summary, language=self.language)

    def _handle_alarm_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"list alarms", "show alarms", "alarms", "my alarms"}:
            return CosmicResponse(message=self.list_alarms(), language=self.language)

        cancel_match = re.match(r"^(?:cancel alarm|remove alarm|delete alarm)\s*(?P<index>\d+)?$", normalized)
        if cancel_match:
            index_text = cancel_match.group("index")
            if not index_text:
                return CosmicResponse(message=self._msg("Tell me which alarm number to cancel.", "bataiye kaun sa alarm cancel karna hai."), language=self.language)
            removed = self.cancel_alarm(int(index_text))
            if removed:
                return CosmicResponse(message=self._msg(f"I cancelled alarm {index_text}.", f"maine alarm {index_text} cancel kar diya."), language=self.language)
            return CosmicResponse(message=self._msg("I could not find that alarm.", "mujhe woh alarm nahi mila."), language=self.language)

        alarm_match = re.match(r"^(?:set alarm|alarm)\s+(?P<when>.+?)\s+(?:to|for|about)\s+(?P<task>.+)$", normalized, flags=re.IGNORECASE)
        if not alarm_match:
            return None

        when_text = alarm_match.group("when").strip()
        if when_text.lower().startswith("for "):
            when_text = when_text[4:].strip()
        if not when_text.lower().startswith(("in ", "at ", "tomorrow")):
            when_text = f"at {when_text}"
        task = alarm_match.group("task").strip()
        when = self._parse_reminder_time(when_text)
        if when is None:
            return CosmicResponse(message=self._msg("Try saying: set alarm for 7 am to wake up.", "aise bolen: set alarm for 7 am to wake up."), language=self.language)

        alarm_id = self.add_alarm(when, task)
        return CosmicResponse(message=self._msg(f"Okay, I set an alarm for {task} at {when.strftime('%I:%M %p on %B %d')}.", f"theek hai, maine {task} ke liye {when.strftime('%d %B %I:%M %p')} par alarm set kar diya."), language=self.language, data={"alarm_id": alarm_id})

    def _handle_screenshot_command(self, normalized: str) -> CosmicResponse | None:
        if normalized not in {"screenshot", "take screenshot", "capture screen", "capture screenshot", "screen shot", "capture current page"}:
            return None
        return CosmicResponse(message=self._msg("Taking a screenshot.", "screenshot le raha hoon."), action="save_screenshot", language=self.language)

    def _handle_translation_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        prefixes = ("translate ", "translation ", "translate and speak ", "speak translate ", "say translate ")
        if not self._starts_with_any(normalized, prefixes):
            return None

        target_lang = None
        if " to hindi" in normalized or normalized.endswith(" hindi"):
            target_lang = "hi"
        elif " to english" in normalized or normalized.endswith(" english"):
            target_lang = "en"
        else:
            return CosmicResponse(message=self._msg("Say something like: translate hello to hindi.", "aise bolen: translate hello to hindi."), language=self.language)

        source_text = self._raw_argument(raw_command, "translate and speak ")
        if not source_text:
            source_text = self._raw_argument(raw_command, "speak translate ")
        if not source_text:
            source_text = self._raw_argument(raw_command, "say translate ")
        if not source_text:
            source_text = self._raw_argument(raw_command, "translate ")
        if not source_text:
            source_text = self._raw_argument(raw_command, "translation ")
        if " to hindi" in source_text.lower():
            source_text = source_text[: source_text.lower().rfind(" to hindi")].strip()
        if " to english" in source_text.lower():
            source_text = source_text[: source_text.lower().rfind(" to english")].strip()

        if not source_text:
            return CosmicResponse(message=self._msg("Tell me what text to translate.", "bataiye kya translate karna hai."), language=self.language)

        translated = self._translate_text(source_text, target_lang)
        if not translated:
            return CosmicResponse(message=self._msg("I could not translate that right now.", "abhi main usse translate nahi kar pa raha hoon."), language=self.language)

        return CosmicResponse(message=translated, language=target_lang)

    def _handle_planner_command(self, normalized: str) -> CosmicResponse | None:
        if normalized not in {"daily planner", "plan my day", "my day", "plan day", "daily plan", "day plan"}:
            return None

        now = dt.datetime.now()
        today_label = now.strftime("%A, %B %d")
        reminders = [item for item in self.reminders if not item.get("done")]
        events = [item for item in self.calendar_events if not item.get("done")]
        timers = [item for item in self.timers if not item.get("done")]
        alarms = [item for item in self.alarms if not item.get("done")]

        sections: list[str] = [f"Here is your plan for {today_label}."]

        if events:
            upcoming = []
            for item in events[:3]:
                title = str(item.get("title", "")).strip()
                when_text = self._format_datetime(str(item.get("when", "")))
                if title:
                    upcoming.append(f"{title} at {when_text}")
            if upcoming:
                sections.append("Calendar: " + "; ".join(upcoming))

        if reminders:
            upcoming = []
            for item in reminders[:3]:
                text = str(item.get("text", "")).strip()
                when_text = self._format_datetime(str(item.get("when", "")))
                if text:
                    upcoming.append(f"{text} at {when_text}")
            if upcoming:
                sections.append("Reminders: " + "; ".join(upcoming))

        if timers:
            active = []
            for item in timers[:3]:
                label = str(item.get("text", "")).strip()
                when_text = self._format_datetime(str(item.get("when", "")))
                if label:
                    active.append(f"{label} at {when_text}")
            if active:
                sections.append("Timers: " + "; ".join(active))

        if alarms:
            active = []
            for item in alarms[:3]:
                label = str(item.get("text", "")).strip()
                when_text = self._format_datetime(str(item.get("when", "")))
                if label:
                    active.append(f"{label} at {when_text}")
            if active:
                sections.append("Alarms: " + "; ".join(active))

        if len(sections) == 1:
            sections.append("You have nothing scheduled yet.")

        return CosmicResponse(message=" ".join(sections), language=self.language)

    def _handle_quick_reply_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        replies = {
            "reply busy": "I’m busy right now, I’ll text you later.",
            "reply call you later": "I’ll call you later.",
            "reply on my way": "I’m on my way.",
            "reply yes": "Yes, sure.",
            "reply no": "No, sorry.",
            "reply thanks": "Thank you.",
            "reply good morning": "Good morning.",
            "reply good night": "Good night.",
            "reply i am cosmic": "Hi, I’m Cosmic.",
        }
        if normalized in replies:
            return CosmicResponse(
                message=f"Copied quick reply: {replies[normalized]}",
                action="set_clipboard",
                data={"text": replies[normalized]},
                language=self.language,
            )

        quick_match = re.match(r"^(?:quick reply|reply template|template)\s+(?P<name>.+)$", normalized)
        if not quick_match:
            return None

        template = quick_match.group("name").strip()
        template_map = {
            "busy": "I’m busy right now, I’ll text you later.",
            "call you later": "I’ll call you later.",
            "on my way": "I’m on my way.",
            "yes": "Yes, sure.",
            "no": "No, sorry.",
            "thanks": "Thank you.",
            "good morning": "Good morning.",
            "good night": "Good night.",
            "i am cosmic": "Hi, I’m Cosmic.",
        }
        text = template_map.get(template)
        if not text:
            return CosmicResponse(message=self._msg("I do not know that quick reply template.", "mujhe ye quick reply template nahi pata."), language=self.language)

        return CosmicResponse(
            message=f"Copied quick reply: {text}",
            action="set_clipboard",
            data={"text": text},
            language=self.language,
        )

    def _handle_note_search_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        prefixes = (
            "search note ",
            "search notes ",
            "find note ",
            "find notes ",
            "look for note ",
            "look for notes ",
            "note search ",
        )
        if not self._starts_with_any(normalized, prefixes):
            return None

        query = ""
        for prefix in prefixes:
            if normalized.startswith(prefix):
                query = self._raw_argument(raw_command, prefix)
                break

        if not query:
            return CosmicResponse(message=self._msg("Tell me what note you want me to search for.", "बताइए कौन सा note search करना है."), language=self.language)

        matches = self.search_notes(query)
        if not matches:
            return CosmicResponse(message=self._msg(f"I could not find any notes about {query}.", f"मुझे {query} पर कोई note नहीं मिला।"), language=self.language)

        return CosmicResponse(
            message=self._msg(
                f"I found {len(matches)} note{'s' if len(matches) != 1 else ''}: " + "; ".join(matches[:5]),
                f"मुझे {len(matches)} note{'s' if len(matches) != 1 else ''} मिले: " + "; ".join(matches[:5]),
            ),
            language=self.language,
        )

    def _handle_file_search_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        open_match = re.match(r"^(?:open file|open search result|open result)\s+(?P<index>\d+)$", normalized)
        if open_match:
            index = int(open_match.group("index"))
            if index < 1 or index > len(self.last_file_search_results):
                return CosmicResponse(message=self._msg("I could not find that search result.", "मुझे वह search result नहीं मिला."), language=self.language)
            path = self.last_file_search_results[index - 1]
            return CosmicResponse(
                message=self._msg(f"Opening file {index}.", f"file {index} खोल रहा हूँ."),
                action="open_path",
                data={"path": path},
                language=self.language,
            )

        prefixes = (
            "find file ",
            "search file ",
            "search files ",
            "find files ",
            "look for file ",
            "look for files ",
            "file search ",
        )
        if not self._starts_with_any(normalized, prefixes):
            return None

        query = ""
        for prefix in prefixes:
            if normalized.startswith(prefix):
                query = self._raw_argument(raw_command, prefix)
                break

        if not query:
            return CosmicResponse(message=self._msg("Tell me what file you want me to search for.", "बताइए कौन सी file search करनी है."), language=self.language)

        results = self.search_files(query)
        self.last_file_search_results = results
        if not results:
            return CosmicResponse(message=self._msg(f"I could not find any files about {query}.", f"मुझे {query} से जुड़ी कोई file नहीं मिली।"), language=self.language)

        lines = [self._format_file_search_result(path, idx + 1) for idx, path in enumerate(results[:5])]
        message = self._msg(
            f"I found {len(results)} file{'s' if len(results) != 1 else ''}: " + "; ".join(lines),
            f"मुझे {len(results)} file{'s' if len(results) != 1 else ''} मिलीं: " + "; ".join(lines),
        )
        return CosmicResponse(message=message, language=self.language)

    def _handle_notes_editor_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"list notes", "show notes", "notes", "notes editor", "notes manager"}:
            summary = self.notes_summary()
            return CosmicResponse(message=summary, language=self.language)

        if normalized in {"open notes folder", "open note folder", "notes folder"}:
            return CosmicResponse(message="Opening the notes folder.", action="open_path", data={"path": self._notes_dir()}, language=self.language)

        open_match = re.match(r"^(?:open note|open notes|read note)\s+(?P<index>\d+)$", normalized)
        if open_match:
            index = int(open_match.group("index"))
            path = self.note_file_path(index)
            if not path:
                return CosmicResponse(message=self._msg("I could not find that note.", "मुझे वह note नहीं मिला."), language=self.language)
            return CosmicResponse(message=self._msg(f"Opening note {index}.", f"note {index} खोल रहा हूँ."), action="open_path", data={"path": path}, language=self.language)

        delete_match = re.match(r"^(?:delete note|remove note|forget note)\s+(?P<index>\d+)$", normalized)
        if delete_match:
            index = int(delete_match.group("index"))
            if self.delete_note_file(index):
                return CosmicResponse(message=self._msg(f"Deleted note {index}.", f"note {index} मिटा दी गई है।"), language=self.language)
            return CosmicResponse(message=self._msg("I could not find that note.", "मुझे वह note नहीं मिला."), language=self.language)

        append_match = re.match(r"^(?:append note|add to note|edit note)\s+(?P<index>\d+)\s+(?P<text>.+)$", normalized)
        if append_match:
            index = int(append_match.group("index"))
            text = append_match.group("text").strip()
            path = self.note_file_path(index)
            if not path:
                return CosmicResponse(message=self._msg("I could not find that note.", "मुझे वह note नहीं मिला."), language=self.language)
            try:
                timestamp = dt.datetime.now().strftime("%H:%M:%S")
                with open(path, "a", encoding="utf-8") as file:
                    file.write(f"[{timestamp}] {text}\n")
                return CosmicResponse(message=self._msg(f"Updated note {index}.", f"note {index} अपडेट कर दी है।"), language=self.language)
            except Exception:
                logger.exception("Failed to append to note %s", path)
                return CosmicResponse(message=self._msg("I could not update that note.", "मैं उस note को update नहीं कर पाया।"), language=self.language)

        return None

    def _handle_macro_command(self, normalized: str) -> CosmicResponse | None:
        macros = {
            "study mode": {"macro": "study"},
            "work mode": {"macro": "work"},
            "bedtime mode": {"macro": "bedtime"},
            "focus mode": {"macro": "focus"},
            "start focus mode": {"macro": "focus"},
            "enable focus mode": {"macro": "focus"},
            "focus mode on": {"macro": "focus"},
            "exit focus mode": {"macro": "normal"},
            "focus mode off": {"macro": "normal"},
            "normal mode": {"macro": "normal"},
            "default mode": {"macro": "normal"},
            "relax mode": {"macro": "relax"},
        }
        if normalized in macros:
            macro = macros[normalized]["macro"]
            return CosmicResponse(
                message=self._msg(
                    f"Switching to {macro} mode.",
                    f"??? {macro} mode ??? ?? ??? ????",
                ),
                action="run_macro",
                data={"macro": macro},
                language=self.language,
            )
        return None

    def _handle_clipboard_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"paste clipboard", "paste copied text", "paste what i copied", "paste from clipboard"}:
            return CosmicResponse(message=self._msg("Pasting the clipboard contents.", "??? clipboard paste ?? ??? ????"), action="paste_clipboard", language=self.language)

        if normalized in {"clipboard manager", "manage clipboard", "clipboard manager open"}:
            summary = self.clipboard_manager_summary()
            return CosmicResponse(message=summary, language=self.language)

        if normalized in {"clear clipboard history", "delete clipboard history", "empty clipboard history"}:
            self.clear_clipboard_history()
            return CosmicResponse(message=self._msg("Clipboard history cleared.", "clipboard history साफ कर दी गई है।"), language=self.language)

        copy_match = re.match(r"^(?:copy clipboard|copy history|copy item)\s+(?P<index>\d+)$", normalized)
        if copy_match:
            index = int(copy_match.group("index"))
            item = self.clipboard_history_item(index)
            if not item:
                return CosmicResponse(message=self._msg("I could not find that clipboard item.", "मुझे वह clipboard item नहीं मिला."), language=self.language)
            return CosmicResponse(
                message=self._msg(f"Copied clipboard item {index}.", f"clipboard item {index} कॉपी कर दिया है।"),
                action="set_clipboard",
                data={"text": item},
                language=self.language,
            )

        remove_match = re.match(r"^(?:remove clipboard|delete clipboard|forget clipboard)\s+(?P<index>\d+)$", normalized)
        if remove_match:
            index = int(remove_match.group("index"))
            if self.remove_clipboard_history_item(index):
                return CosmicResponse(message=self._msg(f"Removed clipboard item {index}.", f"clipboard item {index} हटा दिया गया है।"), language=self.language)
            return CosmicResponse(message=self._msg("I could not find that clipboard item.", "मुझे वह clipboard item नहीं मिला."), language=self.language)

        paste_history_match = re.match(r"^(?:paste clipboard|paste history|paste copied|paste item)\s+(?P<index>\d+)$", normalized)
        if paste_history_match:
            index = int(paste_history_match.group("index"))
            item = self.clipboard_history_item(index)
            if not item:
                return CosmicResponse(message=self._msg("I could not find that clipboard item.", "mujhe woh clipboard item nahi mila."), language=self.language)
            return CosmicResponse(
                message=self._msg(f"Pasting clipboard item {index}.", f"clipboard item {index} paste kar raha hoon."),
                action="set_clipboard_and_paste",
                data={"text": item},
                language=self.language,
            )

        if normalized in {"clipboard history", "show clipboard history", "list clipboard history", "history clipboard"}:
            return CosmicResponse(message=self.clipboard_history_summary(), language=self.language)

        if normalized in {"read clipboard", "what is in clipboard", "show clipboard", "clipboard"}:
            return CosmicResponse(message=self._msg("Reading the clipboard.", "??? clipboard ??? ??? ????"), action="read_clipboard", language=self.language)

        if self._starts_with_any(normalized, ("copy ", "copy text ", "copy this ", "paste text ")):
            text = self._raw_argument(raw_command, "copy ")
            if not text:
                text = self._raw_argument(raw_command, "copy text ")
            if not text:
                text = self._raw_argument(raw_command, "copy this ")
            if not text:
                text = self._raw_argument(raw_command, "paste text ")
            if text:
                self.remember_clipboard_item(text)
                return CosmicResponse(message=self._msg("Copied it to the clipboard.", "????? ??? clipboard ??? copy ?? ?????"), action="set_clipboard", data={"text": text}, language=self.language)
        return None

    def _handle_timer_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        if normalized in {"list timers", "show timers", "timers", "my timers"}:
            return CosmicResponse(message=self.list_timers(), language=self.language)

        cancel_match = re.match(r"^(?:cancel timer|remove timer|delete timer)\s*(?P<index>\d+)?$", normalized)
        if cancel_match:
            index_text = cancel_match.group("index")
            if not index_text:
                return CosmicResponse(message=self._msg("Tell me which timer number to cancel.", "bataiye kaun sa timer cancel karna hai."), language=self.language)
            removed = self.cancel_timer(int(index_text))
            if removed:
                return CosmicResponse(message=self._msg(f"I cancelled timer {index_text}.", f"maine timer {index_text} cancel kar diya."), language=self.language)
            return CosmicResponse(message=self._msg("I could not find that timer.", "mujhe woh timer nahi mila."), language=self.language)

        if normalized in {"start stopwatch", "begin stopwatch", "run stopwatch"}:
            return CosmicResponse(message=self.start_stopwatch(), language=self.language)

        if normalized in {"stop stopwatch", "pause stopwatch"}:
            return CosmicResponse(message=self.stop_stopwatch(), language=self.language)

        if normalized in {"reset stopwatch", "clear stopwatch"}:
            return CosmicResponse(message=self.reset_stopwatch(), language=self.language)

        if normalized in {"stopwatch", "watch stopwatch", "stopwatch status", "show stopwatch"}:
            return CosmicResponse(message=self.stopwatch_status(), language=self.language)

        timer_match = re.match(r"^(?:set timer|start timer|timer)\s+(?P<details>.+)$", normalized, flags=re.IGNORECASE)
        if not timer_match:
            return None

        details = timer_match.group("details").strip()
        if details.lower().startswith("for "):
            details = details[4:].strip()

        label = "timer"
        label_match = re.match(r"^(?P<when>(?:in\s+)?\d+\s*(?:seconds?|minutes?|hours?))(?:\s+(?:to|for|about)\s+(?P<label>.+))?$", details, flags=re.IGNORECASE)
        if label_match:
            when_text = label_match.group("when").strip()
            label = (label_match.group("label") or label).strip()
        else:
            when_text = details
            split = re.match(r"^(?P<when>.+?)\s+(?:to|for|about)\s+(?P<label>.+)$", details, flags=re.IGNORECASE)
            if split:
                when_text = split.group("when").strip()
                label = split.group("label").strip() or label

        when = self._parse_snooze_time(when_text)
        if when is None:
            return CosmicResponse(
                message=self._msg(
                    "Try saying: timer 10 minutes, or set timer for 10 minutes to drink water.",
                    "aise bolen: timer 10 minutes, ya set timer for 10 minutes to drink water.",
                ),
                language=self.language,
            )

        timer_id = self.add_timer(when, label)
        display_label = label if label != "timer" else "this timer"
        return CosmicResponse(
            message=self._msg(
                f"Okay, I set a timer for {display_label} at {when.strftime('%I:%M %p on %B %d')}.",
                f"theek hai, maine {display_label} ke liye {when.strftime('%d %B %I:%M %p')} par timer set kar diya.",
            ),
            language=self.language,
            data={"timer_id": timer_id},
        )

    def _handle_incoming_message_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        prefixes = (
            "received message from ",
            "receive message from ",
            "message from ",
            "new message from ",
            "reply to ",
            "reply message from ",
            "text from ",
            "message received from ",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                contact = self._raw_argument(raw_command, prefix)
                return self._start_reply_flow(contact)
        return None

    def _find_reminder_for_snooze(self, target: str) -> dict[str, object] | None:
        active = [item for item in self.reminders if not item.get("done")]
        if not active:
            return None

        if target in {"", "last", "it", "this"}:
            if self.last_announced_reminders:
                last = self.last_announced_reminders[-1]
                reminder_id = last.get("id")
                if reminder_id is not None:
                    for item in reversed(active):
                        if str(item.get("id", "")) == str(reminder_id):
                            return item
            return active[-1]

        if target.isdigit():
            index = int(target)
            if 1 <= index <= len(active):
                return active[index - 1]

        return None

    def _start_reply_flow(self, contact: str) -> CosmicResponse:
        contact = contact.strip()
        if not contact:
            return CosmicResponse(message=self._msg("Tell me who sent the message.", "बताइए किसने message भेजा है।"))

        self.pending_action = "reply_message"
        self.pending_contact_name = contact
        self.pending_contact_number = ""
        self.pending_message_text = ""

        return CosmicResponse(
            message=self._msg(
                f"You received a message from {contact}. I am Cosmic. Tell me the message you want to give to {contact}.",
                f"आपको {contact} से message मिला है। मैं Cosmic हूँ। {contact} को भेजने के लिए message बताइए।",
            )
        )

    def _split_calendar_event_details(self, text: str) -> tuple[str, str] | None:
        cleaned = text.strip()
        if not cleaned:
            return None

        duration = r"(?:in\s+\d+\s*(?:seconds?|minutes?|hours?)|tomorrow at \d{1,2}(?::\d{2})?\s*(?:am|pm)?|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
        patterns = (
            rf"^(?P<when>{duration})\s+(?P<title>.+)$",
            rf"^(?P<title>.+?)\s+(?P<when>{duration})$",
        )
        for pattern in patterns:
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if not match:
                continue
            when_text = match.group("when").strip()
            title = match.group("title").strip()
            if when_text.lower().startswith("for "):
                when_text = when_text[4:].strip()
            if when_text and title:
                return when_text, title
        return None

    def _raw_argument(self, raw_command: str, prefix: str) -> str:
        stripped = raw_command.strip()
        lowered = stripped.lower()
        if not lowered.startswith(prefix):
            return ""
        return stripped[len(prefix):].strip()

    def _build_key_action(self, keys_text: str, verb: str) -> CosmicResponse:
        if not keys_text:
            return CosmicResponse(message=self._msg("Tell me which key or shortcut you want me to use.", "बताइए कौन सा key या shortcut चाहिए।"))

        keys = self._parse_keys(keys_text)
        if not keys:
            return CosmicResponse(message=self._msg("I could not understand that key combination.", "मैं उस key combination को नहीं समझ पाया।"))

        if len(keys) == 1:
            return CosmicResponse(message=f"{verb} {keys[0]}.", action="press_key", data={"key": keys[0]})

        joined = " + ".join(keys)
        return CosmicResponse(message=f"{verb} {joined}.", action="hotkey", data={"keys": ",".join(keys)})

    @staticmethod
    def _looks_like_phone_number(text: str) -> bool:
        digits = re.sub(r"\D", "", text)
        return len(digits) >= 7

    def _extract_level_command(
        self,
        normalized: str,
        prefixes: tuple[str, ...],
        keywords: set[str],
        action: str = "set_volume",
        message_label: str = "volume",
    ) -> CosmicResponse | None:
        level_text = ""
        for prefix in prefixes:
            if normalized.startswith(prefix):
                level_text = normalized.removeprefix(prefix).strip()
                break

        if not level_text:
            for keyword in keywords:
                match = re.search(rf"\b{re.escape(keyword)}\s*(?:to\s*)?(?P<level>\d{{1,3}})\b", normalized)
                if match:
                    level_text = match.group("level")
                    break

        if not level_text:
            return None

        match = re.search(r"\d{1,3}", level_text)
        if not match:
            return None

        level = max(0, min(100, int(match.group(0))))
        return CosmicResponse(
            message=self._msg(f"Setting {message_label} to {level} percent.", f"{message_label} को {level} प्रतिशत पर सेट कर रहा हूँ।"),
            action=action,
            data={"level": str(level)},
        )

    def _resolve_call_target(self, target: str) -> CosmicResponse:
        if not target:
            return CosmicResponse(message=self._msg("Tell me who or what number you want me to call.", "बताइए किसे या कौन सा नंबर कॉल करना है।"))

        contact_name = target.lower().strip()
        if contact_name in self.contacts:
            number = self.contacts[contact_name]
            return CosmicResponse(
                message=self._msg(f"Opening the call link for {target}.", f"{target} के लिए call link खोल रहा हूँ।"),
                action="open_url",
                data={"url": f"tel:{number}"},
            )

        digits = re.sub(r"\D", "", target)
        plus_prefix = "+" if target.strip().startswith("+") else ""
        if len(digits) >= 7:
            return CosmicResponse(
                message=self._msg(f"Opening the call link for {target}.", f"{target} के लिए call link खोल रहा हूँ।"),
                action="open_url",
                data={"url": f"tel:{plus_prefix}{digits}"},
            )

        if "whatsapp" in contact_name and digits:
            return CosmicResponse(
                message=self._msg(f"Opening WhatsApp for {target}.", f"{target} के लिए WhatsApp खोल रहा हूँ।"),
                action="open_url",
                data={"url": f"https://wa.me/{digits}"},
            )

        if self.contacts:
            matches = [name for name in self.contacts if contact_name in name]
            if len(matches) == 1:
                number = self.contacts[matches[0]]
                return CosmicResponse(
                    message=self._msg(f"Opening the call link for {matches[0]}.", f"{matches[0]} के लिए call link खोल रहा हूँ।"),
                    action="open_url",
                    data={"url": f"tel:{number}"},
                )

        return CosmicResponse(
            message=self._msg(
                "I can open a call link if you give me a phone number, or I can use a saved contact from contacts.json.",
                "अगर आप नंबर बताएँ तो मैं call link खोल सकता हूँ, या contacts.json से saved contact इस्तेमाल कर सकता हूँ।"
            )
        )

    def _handle_whatsapp_message_command(self, raw_command: str, normalized: str) -> CosmicResponse | None:
        prefixes = (
            "send message to ",
            "send whatsapp message to ",
            "whatsapp message to ",
            "message to ",
            "message ",
            "????????? ?? ",
            "????????? ?? ",
            "????????? ????? ",
            "????? ???? ",
            "????? ???? ",
            "????? ",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                remainder = self._raw_argument(raw_command, prefix)
                contact, message = self._split_contact_and_message(remainder)
                if not contact:
                    return CosmicResponse(message=self._msg("Tell me who the message is for.", "????? ????? ???? ????? ???"))
                if not message:
                    self.pending_action = "whatsapp_message"
                    self.pending_contact_name = contact
                    return CosmicResponse(message=self._msg(f"What message should I send to {contact}?", f"{contact} ?? ???? ????? ??????"))
                return self._send_whatsapp_message(contact, message)

        whatsapp_match = re.match(r"whatsapp chat with (.+?) and send (.+)$", normalized)
        if whatsapp_match:
            contact = whatsapp_match.group(1).strip()
            message = self._raw_argument(raw_command, f"open whatsapp chat with {contact} and send ")
            if not message:
                message = whatsapp_match.group(2).strip()
            return self._send_whatsapp_message(contact, message)

        return None

    def _send_whatsapp_message(self, contact: str, message: str, number_override: str = "") -> CosmicResponse:
        if not contact:
            return CosmicResponse(message=self._msg("Tell me who you want me to message.", "????? ???? ????? ????? ???"))
        if not message:
            self.pending_action = "whatsapp_message"
            self.pending_contact_name = contact
            self.pending_message_text = ""
            return CosmicResponse(message=self._msg(f"What message should I send to {contact}?", f"{contact} ?? ???? ????? ??????"))

        number = self._normalize_phone_number(number_override)
        if not number:
            number = self._lookup_contact_number(contact)
        if not number:
            digits = self._normalize_phone_number(contact)
            if len(digits) >= 7:
                number = digits

        if not number:
            self.pending_action = "whatsapp_message"
            self.pending_contact_name = contact
            self.pending_message_text = message
            return CosmicResponse(
                message=self._msg(
                    f"I could not find {contact}. Add it to contacts.json or say the phone number, then I will send: {message}",
                    f"मैं {contact} का number नहीं ढूंढ पाया। contacts.json में जोड़ें या phone number बताइए, फिर मैं यह message भेज दूँगा: {message}"
                )
            )

        return CosmicResponse(
            message=self._msg(f"Sending WhatsApp message to {contact}.", f"{contact} ?? WhatsApp ????? ??? ??? ????"),
            action="open_url",
            data={"url": f"https://wa.me/{number}?text={quote(message)}"},
        )

    @staticmethod
    def _parse_keys(keys_text: str) -> list[str]:
        cleaned = keys_text.lower().strip()
        cleaned = cleaned.replace(" plus ", "+")
        tokens = re.split(r"[+\s,]+", cleaned)
        aliases = {
            "control": "ctrl",
            "ctrl": "ctrl",
            "command": "win",
            "cmd": "win",
            "windows": "win",
            "option": "alt",
            "return": "enter",
            "escape": "esc",
            "esc": "esc",
            "spacebar": "space",
            "space": "space",
            "tab": "tab",
            "delete": "delete",
            "backspace": "backspace",
        }
        keys: list[str] = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            keys.append(aliases.get(token, token))
        return keys

    @staticmethod
    def _load_contacts() -> dict[str, str]:
        contacts_file = os.path.join(os.path.dirname(__file__), "contacts.json")
        if not os.path.exists(contacts_file):
            return {}

        try:
            with open(contacts_file, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load contacts from %s", contacts_file)
            return {}

        contacts: dict[str, str] = {}
        if isinstance(payload, dict):
            for name, number in payload.items():
                if isinstance(name, str) and isinstance(number, (str, int)):
                    contacts[name.lower().strip()] = str(number).strip()
            return contacts

        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip().lower()
                number = str(item.get("number", "")).strip()
                if name and number:
                    contacts[name] = number
        return contacts

    def _lookup_contact_number(self, contact: str) -> str:
        lookup = contact.lower().strip()
        if lookup in self.contacts:
            return self._normalize_phone_number(self.contacts[lookup])

        matches = [name for name in self.contacts if lookup in name]
        if len(matches) == 1:
            return self._normalize_phone_number(self.contacts[matches[0]])

        return ""

    def _set_contact(self, name: str, number: str) -> None:
        cleaned_name = name.lower().strip()
        cleaned_number = self._normalize_phone_number(number)
        if not cleaned_name or not cleaned_number:
            return
        self.contacts[cleaned_name] = cleaned_number
        self._save_contacts()

    def _save_contacts(self) -> None:
        contacts_file = os.path.join(os.path.dirname(__file__), "contacts.json")
        try:
            with open(contacts_file, "w", encoding="utf-8") as file:
                json.dump(dict(sorted(self.contacts.items())), file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save contacts to %s", contacts_file)

    @staticmethod
    def _memory_file() -> str:
        return os.path.join(os.path.dirname(__file__), "cosmic_memory.json")

    @staticmethod
    def _reminders_file() -> str:
        return os.path.join(os.path.dirname(__file__), "cosmic_reminders.json")

    @classmethod
    def _load_memory(cls) -> dict[str, object]:
        path = cls._memory_file()
        default = {
            "facts": [],
            "profile": {},
            "conversation_mode": True,
            "recent": [],
            "stopwatch": {"running": False, "started_at": "", "elapsed_seconds": 0},
        }
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load memory from %s", path)
            return default
        if not isinstance(payload, dict):
            return default
        payload.setdefault("facts", [])
        payload.setdefault("profile", {})
        payload.setdefault("conversation_mode", True)
        payload.setdefault("recent", [])
        payload.setdefault("stopwatch", {"running": False, "started_at": "", "elapsed_seconds": 0})
        return payload

    @classmethod
    def _save_memory(cls, memory: dict[str, object]) -> None:
        try:
            with open(cls._memory_file(), "w", encoding="utf-8") as file:
                json.dump(memory, file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save memory")

    @classmethod
    def _load_reminders(cls) -> list[dict[str, object]]:
        path = cls._reminders_file()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load reminders from %s", path)
            return []
        if not isinstance(payload, list):
            return []
        reminders: list[dict[str, object]] = []
        for item in payload:
            if isinstance(item, dict):
                reminders.append(item)
        return reminders

    @classmethod
    def _save_reminders(cls, reminders: list[dict[str, object]]) -> None:
        try:
            with open(cls._reminders_file(), "w", encoding="utf-8") as file:
                json.dump(reminders, file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save reminders")

    def record_interaction(self, user_text: str, assistant_text: str) -> None:
        recent = self.memory.setdefault("recent", [])
        if not isinstance(recent, list):
            recent = []
            self.memory["recent"] = recent
        recent.append(
            {
                "user": user_text.strip(),
                "assistant": assistant_text.strip(),
                "time": dt.datetime.now().isoformat(timespec="seconds"),
            }
        )
        del recent[:-12]
        self._save_memory(self.memory)

    def remember_fact(self, key: str, value: str) -> None:
        facts = self.memory.setdefault("facts", [])
        profile = self.memory.setdefault("profile", {})
        if not isinstance(facts, list):
            facts = []
            self.memory["facts"] = facts
        if not isinstance(profile, dict):
            profile = {}
            self.memory["profile"] = profile

        cleaned_key = key.strip().lower()
        cleaned_value = value.strip()
        if cleaned_key == "fact":
            if cleaned_value and cleaned_value not in facts:
                facts.append(cleaned_value)
        else:
            fact_text = f"{cleaned_key}: {cleaned_value}"
            if fact_text and fact_text not in facts:
                facts.append(fact_text)
            profile[cleaned_key] = cleaned_value
        self._save_memory(self.memory)

    def forget_memory(self) -> None:
        self.memory["facts"] = []
        self.memory["profile"] = {}
        self.memory["recent"] = []
        self._save_memory(self.memory)

    def memory_summary(self) -> str:
        facts = self.memory.get("facts", [])
        profile = self.memory.get("profile", {})
        recent = self.memory.get("recent", [])

        parts: list[str] = []
        if isinstance(profile, dict) and profile:
            for key, value in list(profile.items())[:5]:
                parts.append(f"{key}: {value}")
        if isinstance(facts, list) and facts:
            parts.extend(str(item) for item in facts[:5])
        if isinstance(recent, list) and recent:
            last = recent[-1]
            if isinstance(last, dict):
                user = last.get("user", "")
                assistant = last.get("assistant", "")
                if user or assistant:
                    parts.append(f"Last chat: you said '{user}' and I replied '{assistant}'.")

        if not parts:
            return self._msg("I do not have anything saved yet.", "मेरे पास अभी कोई saved memory नहीं है।")
        return self._msg("Here is what I remember: " + "; ".join(parts), "मैं यह याद रखता हूँ: " + "; ".join(parts))

    def add_reminder(self, when: dt.datetime, text: str) -> str:
        reminder = {
            "id": random.randint(100000, 999999),
            "when": when.isoformat(timespec="seconds"),
            "text": text.strip(),
            "done": False,
        }
        self.reminders.append(reminder)
        self._save_reminders(self.reminders)
        return str(reminder["id"])

    def list_reminders(self) -> str:
        active = [item for item in self.reminders if not item.get("done")]
        if not active:
            return self._msg("You do not have any reminders.", "आपके पास कोई reminder नहीं है।")

        lines = []
        for idx, item in enumerate(active, start=1):
            when_text = str(item.get("when", ""))
            text = str(item.get("text", ""))
            lines.append(f"{idx}. {text} at {when_text}")
        return self._msg("Your reminders are: " + "; ".join(lines), "आपके reminders हैं: " + "; ".join(lines))

    def cancel_reminder(self, index: int) -> str:
        active = [item for item in self.reminders if not item.get("done")]
        if index < 1 or index > len(active):
            return ""
        target = active[index - 1]
        target["done"] = True
        self._save_reminders(self.reminders)
        return str(target.get("text", ""))

    def pop_due_reminders(self) -> list[str]:
        now = dt.datetime.now()
        announcements: list[str] = []
        changed = False
        for item in self.reminders:
            if item.get("done"):
                continue
            when_text = str(item.get("when", ""))
            try:
                due_at = dt.datetime.fromisoformat(when_text)
            except Exception:
                continue
            if due_at <= now:
                item["done"] = True
                changed = True
                text = str(item.get("text", "")).strip()
                if text:
                    announcements.append(self._msg(f"Reminder: {text}.", f"रिमाइंडर: {text}।"))
        if changed:
            self._save_reminders(self.reminders)
        return announcements

    @classmethod
    def _load_calendar_events(cls) -> list[dict[str, object]]:
        path = cls._calendar_file()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load calendar events from %s", path)
            return []
        if not isinstance(payload, list):
            return []
        events: list[dict[str, object]] = []
        for item in payload:
            if isinstance(item, dict):
                events.append(item)
        return events

    @classmethod
    def _save_calendar_events(cls, events: list[dict[str, object]]) -> None:
        try:
            with open(cls._calendar_file(), "w", encoding="utf-8") as file:
                json.dump(events, file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save calendar events")

    @staticmethod
    def _calendar_file() -> str:
        return os.path.join(os.path.dirname(__file__), "cosmic_calendar.json")

    def add_calendar_event(self, when: dt.datetime, title: str) -> str:
        event = {
            "id": random.randint(100000, 999999),
            "when": when.isoformat(timespec="seconds"),
            "title": title.strip(),
            "done": False,
        }
        self.calendar_events.append(event)
        self._save_calendar_events(self.calendar_events)
        return str(event["id"])

    def list_calendar_events(self) -> str:
        active = [item for item in self.calendar_events if not item.get("done")]
        if not active:
            return self._msg("You do not have any calendar events.", "aapke paas koi calendar event nahi hai.")
        lines = []
        for idx, item in enumerate(active, start=1):
            when_text = str(item.get("when", ""))
            title = str(item.get("title", ""))
            lines.append(f"{idx}. {title} at {self._format_datetime(when_text)}")
        return self._msg("Your calendar events are: " + "; ".join(lines), "aapke calendar events hain: " + "; ".join(lines))

    def cancel_calendar_event(self, index: int) -> str:
        active = [item for item in self.calendar_events if not item.get("done")]
        if index < 1 or index > len(active):
            return ""
        target = active[index - 1]
        target["done"] = True
        self._save_calendar_events(self.calendar_events)
        return str(target.get("title", ""))

    def pop_due_calendar_events(self) -> list[str]:
        now = dt.datetime.now()
        announcements: list[str] = []
        changed = False
        self.last_announced_calendar_events = []
        for item in self.calendar_events:
            if item.get("done"):
                continue
            when_text = str(item.get("when", ""))
            try:
                due_at = dt.datetime.fromisoformat(when_text)
            except Exception:
                continue
            if due_at <= now:
                item["done"] = True
                changed = True
                title = str(item.get("title", "")).strip()
                if title:
                    announcements.append(self._msg(f"Calendar event: {title}.", f"calendar event: {title}."))
                    self.last_announced_calendar_events.append({"id": item.get("id"), "title": title, "when": when_text})
        if changed:
            self._save_calendar_events(self.calendar_events)
        return announcements

    @classmethod
    def _load_timers(cls) -> list[dict[str, object]]:
        path = cls._timers_file()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load timers from %s", path)
            return []
        if not isinstance(payload, list):
            return []
        timers: list[dict[str, object]] = []
        for item in payload:
            if isinstance(item, dict):
                timers.append(item)
        return timers

    @classmethod
    def _save_timers(cls, timers: list[dict[str, object]]) -> None:
        try:
            with open(cls._timers_file(), "w", encoding="utf-8") as file:
                json.dump(timers, file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save timers")

    @staticmethod
    def _timers_file() -> str:
        return os.path.join(os.path.dirname(__file__), "cosmic_timers.json")

    def add_timer(self, when: dt.datetime, text: str) -> str:
        timer = {
            "id": random.randint(100000, 999999),
            "when": when.isoformat(timespec="seconds"),
            "text": text.strip(),
            "done": False,
        }
        self.timers.append(timer)
        self._save_timers(self.timers)
        return str(timer["id"])

    def list_timers(self) -> str:
        active = [item for item in self.timers if not item.get("done")]
        if not active:
            return self._msg("You do not have any timers.", "aapke paas koi timer nahi hai.")
        lines = []
        for idx, item in enumerate(active, start=1):
            when_text = str(item.get("when", ""))
            text = str(item.get("text", ""))
            lines.append(f"{idx}. {text} at {self._format_datetime(when_text)}")
        return self._msg("Your timers are: " + "; ".join(lines), "aapke timers hain: " + "; ".join(lines))

    def cancel_timer(self, index: int) -> str:
        active = [item for item in self.timers if not item.get("done")]
        if index < 1 or index > len(active):
            return ""
        target = active[index - 1]
        target["done"] = True
        self._save_timers(self.timers)
        return str(target.get("text", ""))

    def pop_due_timers(self) -> list[str]:
        now = dt.datetime.now()
        announcements: list[str] = []
        changed = False
        self.last_announced_timers = []
        for item in self.timers:
            if item.get("done"):
                continue
            when_text = str(item.get("when", ""))
            try:
                due_at = dt.datetime.fromisoformat(when_text)
            except Exception:
                continue
            if due_at <= now:
                item["done"] = True
                changed = True
                text = str(item.get("text", "")).strip()
                if text:
                    announcements.append(self._msg(f"Timer done: {text}.", f"timer: {text}."))
                    self.last_announced_timers.append({"id": item.get("id"), "text": text, "when": when_text})
        if changed:
            self._save_timers(self.timers)
        return announcements

    @classmethod
    def _load_clipboard_history(cls) -> list[str]:
        path = cls._clipboard_history_file()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            logger.exception("Failed to load clipboard history from %s", path)
            return []
        if not isinstance(payload, list):
            return []
        history = [str(item).strip() for item in payload if str(item).strip()]
        return history

    @classmethod
    def _save_clipboard_history(cls, history: list[str]) -> None:
        try:
            with open(cls._clipboard_history_file(), "w", encoding="utf-8") as file:
                json.dump(history, file, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save clipboard history")

    @staticmethod
    def _clipboard_history_file() -> str:
        return os.path.join(os.path.dirname(__file__), "cosmic_clipboard.json")

    def remember_clipboard_item(self, text: str) -> None:
        item = text.strip()
        if not item:
            return
        history = self.clipboard_history if isinstance(self.clipboard_history, list) else []
        if item in history:
            history.remove(item)
        history.insert(0, item)
        del history[20:]
        self.clipboard_history = history
        self._save_clipboard_history(history)

    def remove_clipboard_history_item(self, index: int) -> bool:
        history = self.clipboard_history if isinstance(self.clipboard_history, list) else []
        if index < 1 or index > len(history):
            return False
        del history[index - 1]
        self.clipboard_history = history
        self._save_clipboard_history(history)
        return True

    def clear_clipboard_history(self) -> None:
        self.clipboard_history = []
        self._save_clipboard_history([])

    def clipboard_history_item(self, index: int) -> str:
        if index < 1:
            return ""
        history = self.clipboard_history if isinstance(self.clipboard_history, list) else []
        if index > len(history):
            return ""
        return history[index - 1]

    def clipboard_history_summary(self) -> str:
        history = self.clipboard_history if isinstance(self.clipboard_history, list) else []
        if not history:
            return self._msg("I do not have any clipboard history yet.", "mere paas abhi koi clipboard history nahi hai.")
        lines = [f"{idx}. {item}" for idx, item in enumerate(history[:5], start=1)]
        return self._msg("Clipboard history: " + "; ".join(lines), "clipboard history: " + "; ".join(lines))

    def clipboard_manager_summary(self) -> str:
        history = self.clipboard_history if isinstance(self.clipboard_history, list) else []
        lines = [f"{idx}. {item}" for idx, item in enumerate(history[:5], start=1)]
        if not lines:
            return self._msg(
                "Clipboard manager: no saved items yet. Try copy hello, clipboard history, paste clipboard 1, or clear clipboard history.",
                "Clipboard manager: अभी कोई saved item नहीं है। copy hello, clipboard history, paste clipboard 1, या clear clipboard history try करें।",
            )
        return self._msg(
            "Clipboard manager: " + "; ".join(lines) + ". Try paste clipboard 1, remove clipboard 1, or clear clipboard history.",
            "Clipboard manager: " + "; ".join(lines) + ". Try paste clipboard 1, remove clipboard 1, या clear clipboard history।",
        )

    def _stopwatch_state(self) -> dict[str, object]:
        state = self.memory.get("stopwatch")
        default = {"running": False, "started_at": "", "elapsed_seconds": 0}
        if not isinstance(state, dict):
            self.memory["stopwatch"] = default
            self._save_memory(self.memory)
            return self.memory["stopwatch"]  # type: ignore[return-value]

        state.setdefault("running", False)
        state.setdefault("started_at", "")
        state.setdefault("elapsed_seconds", 0)
        self.memory["stopwatch"] = state
        return state

    def _stopwatch_elapsed_seconds(self) -> int:
        state = self._stopwatch_state()
        elapsed = int(state.get("elapsed_seconds", 0) or 0)
        if state.get("running"):
            started_at = str(state.get("started_at", "")).strip()
            if started_at:
                try:
                    started = dt.datetime.fromisoformat(started_at)
                    elapsed += max(0, int((dt.datetime.now() - started).total_seconds()))
                except Exception:
                    pass
        return max(0, elapsed)

    def start_stopwatch(self) -> str:
        state = self._stopwatch_state()
        if state.get("running"):
            return self._msg("The stopwatch is already running.", "stopwatch pehle se chal raha hai.")
        state["running"] = True
        state["started_at"] = dt.datetime.now().isoformat(timespec="seconds")
        state["elapsed_seconds"] = int(state.get("elapsed_seconds", 0) or 0)
        self._save_memory(self.memory)
        return self._msg("Stopwatch started.", "stopwatch start ho gaya hai.")

    def stop_stopwatch(self) -> str:
        state = self._stopwatch_state()
        if not state.get("running"):
            return self._msg(
                f"The stopwatch is not running. Elapsed time is {self._format_duration(self._stopwatch_elapsed_seconds())}.",
                f"stopwatch chal nahi raha hai. ab tak ka samay {self._format_duration(self._stopwatch_elapsed_seconds())} hai.",
            )
        elapsed = self._stopwatch_elapsed_seconds()
        state["running"] = False
        state["started_at"] = ""
        state["elapsed_seconds"] = elapsed
        self._save_memory(self.memory)
        return self._msg(
            f"Stopped at {self._format_duration(elapsed)}.",
            f"{self._format_duration(elapsed)} par stop kar diya.",
        )

    def reset_stopwatch(self) -> str:
        state = self._stopwatch_state()
        state["running"] = False
        state["started_at"] = ""
        state["elapsed_seconds"] = 0
        self._save_memory(self.memory)
        return self._msg("Stopwatch reset.", "stopwatch reset ho gaya hai.")

    def stopwatch_status(self) -> str:
        state = self._stopwatch_state()
        elapsed = self._stopwatch_elapsed_seconds()
        if state.get("running"):
            return self._msg(
                f"The stopwatch is running. Elapsed time is {self._format_duration(elapsed)}.",
                f"stopwatch chal raha hai. ab tak ka samay {self._format_duration(elapsed)} hai.",
            )
        return self._msg(
            f"The stopwatch is stopped. Last time was {self._format_duration(elapsed)}.",
            f"stopwatch ruk gaya hai. aakhri samay {self._format_duration(elapsed)} tha.",
        )

    @staticmethod
    def _format_datetime(when_text: str) -> str:
        try:
            when = dt.datetime.fromisoformat(when_text)
        except Exception:
            return when_text
        return when.strftime("%I:%M %p on %B %d")

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if secs or not parts:
            parts.append(f"{secs} second{'s' if secs != 1 else ''}")
        return " ".join(parts)

    @staticmethod
    def _notes_dir() -> str:
        return os.path.join(os.path.dirname(__file__), "notes")

    def search_notes(self, query: str) -> list[str]:
        needle = query.strip().lower()
        if not needle:
            return []

        notes_dir = self._notes_dir()
        if not os.path.isdir(notes_dir):
            return []

        matches: list[str] = []
        try:
            for name in sorted(os.listdir(notes_dir)):
                if not name.lower().endswith(".txt"):
                    continue
                path = os.path.join(notes_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        lines = file.readlines()
                except Exception:
                    continue

                for line in lines:
                    text = line.strip()
                    if not text or needle not in text.lower():
                        continue
                    snippet = text
                    if len(snippet) > 120:
                        snippet = snippet[:117].rstrip() + "..."
                    matches.append(f"{name}: {snippet}")
                    if len(matches) >= 5:
                        return matches
        except Exception:
            logger.exception("Failed to search notes")
        return matches

    def note_files(self) -> list[str]:
        notes_dir = self._notes_dir()
        if not os.path.isdir(notes_dir):
            return []
        try:
            return [
                os.path.join(notes_dir, name)
                for name in sorted(os.listdir(notes_dir))
                if name.lower().endswith(".txt")
            ]
        except Exception:
            logger.exception("Failed to list notes")
            return []

    def note_file_path(self, index: int) -> str:
        files = self.note_files()
        if index < 1 or index > len(files):
            return ""
        return files[index - 1]

    def delete_note_file(self, index: int) -> bool:
        path = self.note_file_path(index)
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except Exception:
            logger.exception("Failed to delete note file %s", path)
            return False

    def notes_summary(self) -> str:
        files = self.note_files()
        if not files:
            return self._msg("I do not have any notes yet.", "अभी कोई notes नहीं हैं।")
        lines = [f"{idx}. {os.path.basename(path)}" for idx, path in enumerate(files[:8], start=1)]
        return self._msg(
            "Notes: " + "; ".join(lines) + ". Try open note 1 or delete note 1.",
            "Notes: " + "; ".join(lines) + ". Try open note 1 or delete note 1.",
        )

    def _common_search_roots(self) -> list[str]:
        home = os.path.expanduser("~")
        roots = [
            os.getcwd(),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Pictures"),
            os.path.join(home, "Music"),
            os.path.join(home, "Videos"),
        ]
        unique_roots: list[str] = []
        for root in roots:
            if root and root not in unique_roots and os.path.exists(root):
                unique_roots.append(root)
        return unique_roots

    def search_files(self, query: str, limit: int = 10) -> list[str]:
        needle = query.strip().lower()
        if not needle:
            return []

        results: list[str] = []
        seen: set[str] = set()
        try:
            scanned_dirs = 0
            max_dirs = 900
            max_depth = 3
            for root in self._common_search_roots():
                for current_root, dirs, files in os.walk(root):
                    scanned_dirs += 1
                    if scanned_dirs > max_dirs:
                        return results
                    depth = current_root[len(root):].count(os.sep)
                    if depth >= max_depth:
                        dirs[:] = []
                    dirs[:] = [name for name in dirs if not name.startswith(".")]
                    for name in files:
                        path = os.path.join(current_root, name)
                        lowered = name.lower()
                        full_lower = path.lower()
                        if needle in lowered or needle in full_lower:
                            normalized_path = os.path.normpath(path)
                            if normalized_path not in seen:
                                seen.add(normalized_path)
                                results.append(normalized_path)
                            if len(results) >= limit:
                                return results
        except Exception:
            logger.exception("Failed to search files for %s", query)
        return results

    @staticmethod
    def _format_file_search_result(path: str, index: int) -> str:
        folder = os.path.basename(os.path.dirname(path)) or os.path.dirname(path)
        return f"{index}. {os.path.basename(path)} ({folder})"

    @staticmethod
    def _split_contact_and_message(text: str) -> tuple[str, str]:
        cleaned = text.strip()
        if not cleaned:
            return "", ""

        lower = cleaned.lower()
        separators = (" and send ", " say ", " message ", " text ")
        for separator in separators:
            if separator in lower:
                index = lower.index(separator)
                contact = cleaned[:index].strip()
                message = cleaned[index + len(separator):].strip()
                if contact and message:
                    return contact, message

        parts = cleaned.split(maxsplit=1)
        if len(parts) == 1:
            return parts[0], ""

        return parts[0], parts[1]

    def _resolve_open_target(self, target: str) -> CosmicResponse:
        target = self._canonical_open_target(target)
        folder_targets = {
            "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
            "downloads folder": os.path.join(os.path.expanduser("~"), "Downloads"),
            "download folder": os.path.join(os.path.expanduser("~"), "Downloads"),
            "documents": os.path.join(os.path.expanduser("~"), "Documents"),
            "documents folder": os.path.join(os.path.expanduser("~"), "Documents"),
            "document folder": os.path.join(os.path.expanduser("~"), "Documents"),
            "pictures": os.path.join(os.path.expanduser("~"), "Pictures"),
            "pictures folder": os.path.join(os.path.expanduser("~"), "Pictures"),
            "photo folder": os.path.join(os.path.expanduser("~"), "Pictures"),
            "photos": os.path.join(os.path.expanduser("~"), "Pictures"),
            "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
            "desktop folder": os.path.join(os.path.expanduser("~"), "Desktop"),
            "music folder": os.path.join(os.path.expanduser("~"), "Music"),
            "music": os.path.join(os.path.expanduser("~"), "Music"),
            "videos": os.path.join(os.path.expanduser("~"), "Videos"),
            "videos folder": os.path.join(os.path.expanduser("~"), "Videos"),
            "video folder": os.path.join(os.path.expanduser("~"), "Videos"),
        }
        if target in folder_targets:
            pretty = target.replace(" folder", "")
            return CosmicResponse(
                message=self._msg(f"Opening {pretty}.", f"{pretty} खोल रहा हूँ।"),
                action="open_path",
                data={"path": folder_targets[target]},
                language=self.language,
            )

        if target in {"screenshots folder", "screenshot folder", "screenshots", "screenshot folder in cosmic"}:
            folder = os.path.join(os.path.dirname(__file__), "screenshots")
            return CosmicResponse(
                message=self._msg("Opening the screenshots folder.", "Screenshots folder खोल रहा हूँ।"),
                action="open_path",
                data={"path": folder},
                language=self.language,
            )

        whatsapp_match = re.match(r"whatsapp chat with (.+)", target)
        if whatsapp_match:
            contact = whatsapp_match.group(1).strip()
            return self._resolve_whatsapp_chat(contact)

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
            return CosmicResponse(
                message=self._msg(f"Sure, opening {target}.", f"ठीक है, {target} खोल रहा हूँ।"),
                action="open_url",
                data={"url": websites[target]},
                language=self.language,
            )

        apps = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "cmd": "cmd.exe",
            "command prompt": "cmd.exe",
            "powershell": "powershell.exe",
            "file explorer": "explorer.exe",
            "explorer": "explorer.exe",
            "paint": "mspaint.exe",
            "task manager": "taskmgr.exe",
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
            "word": "WINWORD.EXE",
            "excel": "EXCEL.EXE",
            "powerpoint": "POWERPNT.EXE",
            "outlook": "OUTLOOK.EXE",
            "whatsapp": "whatsapp.exe",
            "discord": "Discord.exe",
            "spotify": "Spotify.exe",
            "telegram": "Telegram.exe",
            "teams": "ms-teams.exe",
            "zoom": "Zoom.exe",
            "slack": "slack.exe",
        }

        if target in apps:
            return CosmicResponse(
                message=self._msg(f"Opening {target} now.", f"{target} खोल रहा हूँ।"),
                action="open_app",
                data={"app_name": apps[target]},
                language=self.language,
            )

        path = os.path.expanduser(target)
        if os.path.exists(path):
            return CosmicResponse(
                message=self._msg(f"Opening {target} now.", f"{target} खोल रहा हूँ।"),
                action="open_path",
                data={"path": path},
                language=self.language,
            )

        return CosmicResponse(
            message=self._msg(
                f"I couldn’t find a direct match, so I’m searching for {target}.",
                f"मुझे सीधा match नहीं मिला, इसलिए मैं {target} खोज रहा हूँ।",
            ),
            action="open_url",
            data={"url": f"https://www.google.com/search?q={quote(target)}"},
            language=self.language,
        )

    @staticmethod
    def _canonical_open_target(target: str) -> str:
        cleaned = re.sub(r"\s+", " ", target.lower().strip())
        aliases = {
            "युटुब": "youtube",
            "यूट्यूब": "youtube",
            "यु ट्यूब": "youtube",
            "यू ट्यूब": "youtube",
            "yt": "youtube",
            "utube": "youtube",
            "u tube": "youtube",
            "व्हाट्सऐप": "whatsapp",
            "वॉट्सऐप": "whatsapp",
            "व्हाट्सएप": "whatsapp",
            "वॉट्सएप": "whatsapp",
            "वाट्सऐप": "whatsapp",
            "whats app": "whatsapp",
            "watsapp": "whatsapp",
            "नोटपैड": "notepad",
            "नोट पैड": "notepad",
            "कैलकुलेटर": "calculator",
            "गणक": "calculator",
            "फाइल एक्सप्लोरर": "file explorer",
            "फाइल explorer": "file explorer",
            "कमान्ड प्रॉम्प्ट": "command prompt",
            "कमांड प्रॉम्प्ट": "command prompt",
            "गूगल": "google",
            "जीमेल": "gmail",
            "डिस्कॉर्ड": "discord",
            "स्पॉटिफाई": "spotify",
            "टेलीग्राम": "telegram",
            "टीम्स": "teams",
            "जूम": "zoom",
            "स्लैक": "slack",
        }
        if cleaned in aliases:
            return aliases[cleaned]
        if "youtube" in cleaned or "युटुब" in cleaned or "यूट्यूब" in cleaned:
            return "youtube"
        if "whatsapp" in cleaned or "वॉट्स" in cleaned or "व्हाट्स" in cleaned:
            return "whatsapp"
        if "notepad" in cleaned or "नोटपैड" in cleaned or "नोट पैड" in cleaned:
            return "notepad"
        if "calculator" in cleaned or "कैलकुलेटर" in cleaned or "गणक" in cleaned:
            return "calculator"
        if "chrome" in cleaned or "क्रोम" in cleaned:
            return "chrome"
        if "edge" in cleaned or "एज" in cleaned:
            return "edge"
        if "explorer" in cleaned or "फाइल" in cleaned and "एक्सप्लोर" in cleaned:
            return "file explorer"
        if "desktop" in cleaned or "डेस्कटॉप" in cleaned:
            return "desktop"
        if "downloads" in cleaned or "डाउनलोड" in cleaned:
            return "downloads"
        if "documents" in cleaned or "डॉक्यूमेंट" in cleaned:
            return "documents"
        if "pictures" in cleaned or "photos" in cleaned or "इमेज" in cleaned:
            return "pictures"
        if "music" in cleaned or "म्यूजिक" in cleaned:
            return "music"
        if "videos" in cleaned or "वीडियो" in cleaned:
            return "videos"
        return cleaned

    def _resolve_whatsapp_chat(self, contact: str) -> CosmicResponse:
        if not contact:
            self.pending_action = "whatsapp_chat"
            return CosmicResponse(message=self._msg("Tell me the contact name or phone number for WhatsApp.", "WhatsApp के लिए contact name या phone number बताइए।"), language=self.language)

        lookup = contact.lower().strip()
        if lookup in self.contacts:
            number = self._normalize_phone_number(self.contacts[lookup])
            if not number:
                logger.warning("Stored WhatsApp contact %r had an invalid phone number", lookup)
                return CosmicResponse(message=self._msg(f"I found {contact}, but its phone number looks invalid.", f"मुझे {contact} मिला, लेकिन उसका phone number invalid लग रहा है।"), language=self.language)
            return CosmicResponse(
                message=self._msg(f"Opening WhatsApp chat with {contact}.", f"{contact} का WhatsApp chat खोल रहा हूँ।"),
                action="open_url",
                data={"url": f"https://wa.me/{number}"},
                language=self.language,
            )

        digits = self._normalize_phone_number(contact)
        if len(digits) >= 7:
            return CosmicResponse(
                message=self._msg(f"Opening WhatsApp chat with {contact}.", f"{contact} का WhatsApp chat खोल रहा हूँ।"),
                action="open_url",
                data={"url": f"https://wa.me/{digits}"},
                language=self.language,
            )

        if self.contacts:
            matches = [name for name in self.contacts if lookup in name]
            if len(matches) == 1:
                number = self._normalize_phone_number(self.contacts[matches[0]])
                if not number:
                    logger.warning("Stored WhatsApp contact %r had an invalid phone number", matches[0])
                    return CosmicResponse(message=self._msg(f"I found {matches[0]}, but its phone number looks invalid.", f"मुझे {matches[0]} मिला, लेकिन उसका phone number invalid लग रहा है।"), language=self.language)
                return CosmicResponse(
                    message=self._msg(f"Opening WhatsApp chat with {matches[0]}.", f"{matches[0]} का WhatsApp chat खोल रहा हूँ।"),
                    action="open_url",
                    data={"url": f"https://wa.me/{number}"},
                    language=self.language,
                )

        return CosmicResponse(
            message=self._msg(
                "I could not find that contact. Say the phone number directly, or add the person to contacts.json.",
                "मुझे वह contact नहीं मिला। सीधे phone number बोलिए या उसे contacts.json में जोड़िए।",
            ),
            language=self.language,
        )

    @staticmethod
    def normalize_command(command: str) -> str:
        cleaned = command.lower().strip()
        cleaned_chars: list[str] = []
        for char in cleaned:
            category = unicodedata.category(char)
            if char.isspace() or char.isalnum() or category.startswith("M"):
                cleaned_chars.append(char)
        cleaned = "".join(cleaned_chars)
        for wake in {"cosmic", "assistant", "alexa", "jarvis", "nova"}:
            cleaned = re.sub(rf"\b{re.escape(wake)}\b", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _starts_with_any(text: str, prefixes: tuple[str, ...]) -> bool:
        return any(text.startswith(prefix) for prefix in prefixes)

    @staticmethod
    def _strip_any_prefix(text: str, prefixes: tuple[str, ...]) -> str:
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text.strip()

    @staticmethod
    def _contains_any(text: str, phrases: set[str]) -> bool:
        
        return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) for phrase in phrases)

    @staticmethod
    def jokes() -> list[str]:
        return [
            "Why did the computer go to the doctor? It caught a virus.",
            "I would tell you a UDP joke, but you might not get it.",
            "Why do programmers prefer dark mode? Because light attracts bugs.",
        ]

    def help_text(self) -> str:
        if self.language == "hi":
            return (
                "Quick guide: समय और तारीख; search और Wikipedia; notes, reminders, alarms, timers; "
                "clipboard history; screenshots; translate text; focus mode; volume और brightness; "
                "typing और keyboard shortcuts; apps और websites; call और WhatsApp; help बोलो full command list के लिए।"
            )

        return (
            "Quick guide:\n"
            "• Voice and chat: hello, who are you, what can you do, what do you remember\n"
            "• Search: search Python tutorials, who is Nikola Tesla, wikipedia Python\n"
            "• Notes and files: note buy milk, search note python, list notes, open note 1, delete note 1, file search invoice, open file 1\n"
            "• Productive tools: daily briefing, weather, reminders, alarms, timer 10 minutes, stopwatch, screenshot, translate hello to hindi\n"
            "• Control: open notepad, open screenshots folder, focus mode, focus mode off, volume 50, brightness 70, scroll current page, scroll faster\n"
            "• Clipboard: clipboard manager, copy clipboard 1, paste clipboard 1, clear clipboard history\n"
            "• Messaging: call 9876543210, send message to mom hello, open whatsapp chat with mom\n"
            "• Say help again for the full list."
        )

    def command_guide(self) -> str:
        if self.language == "hi":
            return (
                "कमांड गाइड:\n"
                "• बोलकर बात करें: नमस्ते, आप कौन हैं, आप क्या कर सकते हैं, आप क्या याद रखते हैं\n"
                "• खोज: search Python tutorials, who is Nikola Tesla, wikipedia Python\n"
                "• नोट्स और files: note लिखो, search note python, list notes, open note 1, delete note 1, file search invoice, open file 1\n"
                "• Productivity: daily briefing, weather, reminders, alarms, timer 10 minutes, stopwatch, screenshot, translate hello to hindi\n"
                "• Control: open notepad, open screenshots folder, focus mode, focus mode off, volume 50, brightness 70, scroll current page, scroll faster\n"
                "• Clipboard: clipboard manager, copy clipboard 1, paste clipboard 1, clear clipboard history\n"
                "• Messaging: call 9876543210, send message to mom hello, open whatsapp chat with mom\n"
                "• help बोलो full command list के लिए।"
            )

        return (
            "Try saying: hello, who are you, what can you do, what do you remember; "
            "time, date, daily briefing; search Python tutorials, who is Nikola Tesla, wikipedia Python; "
            "open notepad, open whatsapp, open screenshots folder; play lo-fi music; "
            "type hello there, note buy milk, search note python, find note meeting, list notes, open note 1, delete note 1, press enter, hotkey ctrl c; "
            "scroll current page, scroll a little, scroll a lot, scroll faster, scroll slower, scroll up, scroll down, click, double click, move mouse up 100; "
            "call 9876543210, send message to mom hello, open whatsapp chat with mom; "
            "remember this is my maa mobile no 9876543210, remember that my name is Aniket, conversation mode, command mode; "
            "daily planner, plan my day; remind me in 10 minutes to drink water, list reminders, snooze reminder 1 for 10 minutes; "
            "clipboard manager, clear clipboard history, remove clipboard 1, copy clipboard 1, paste clipboard 1; "
            "file search, search file invoice, open file 1; "
            "search note python, find note meeting, list notes, open note 1, delete note 1, edit note 1 buy milk; "
            "add event tomorrow at 5 pm team meeting, calendar, list events, cancel event 1; "
            "timer 10 minutes, list timers, cancel timer 1, start stopwatch, stop stopwatch, reset stopwatch; "
            "clipboard, copy hello, read clipboard, clipboard history, paste clipboard 2; "
            "weather, set alarm for 7 am to wake up, screenshot, translate hello to hindi, translate and speak hello to hindi; "
            "open downloads, open documents, open pictures, open desktop; quick reply busy, quick reply call you later, reply on my way; "
            "study mode, work mode, focus mode, focus mode off, normal mode, set volume 50, brightness 70, lock the computer, shutdown, restart, sleep, log off."
        )

    @staticmethod
    def _extract_output_text(response: object) -> str:
        chunks: list[str] = []
        output = getattr(response, "output", None) or []
        for item in output:
            content = getattr(item, "content", None) or []
            for part in content:
                text = getattr(part, "text", None)
                if text:
                    chunks.append(text)
        return "".join(chunks)
