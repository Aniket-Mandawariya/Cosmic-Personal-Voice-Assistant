const form = document.getElementById("commandForm");
const input = document.getElementById("commandInput");
const micBtn = document.getElementById("micBtn");
const stopBtn = document.getElementById("stopBtn");
const statusEl = document.getElementsByClassName("status");
const statusBadge = document.getElementById("statusBadge");
const speechIcon = document.getElementById("speechIcon");
const speechWaveform = document.getElementById("speechWaveform");
const conversation = document.getElementById("conversation");
const quickCommands = document.querySelectorAll("[data-command]");

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
let autoRestart = false;
let manualStop = false;
let speechPaused = false;
let speechResumeNeeded = false;
let currentLanguage = "en";
let availableVoices = [];
let micRestartQueued = false;
let recognitionRunning = false;
let recognitionRestartTimer = null;
let speechCooldownUntil = 0;
let ignoreRecognitionUntil = 0;

function updateMicUi(active) {
    listening = active;
    micBtn.textContent = active ? "Stop Listening" : "Start Listening";
    setStatus(active ? "Listening..." : "Ready.");
}

function startListeningSoon(delay = 150) {
    if (!recognition || manualStop) {
        return;
    }
    if (!listening || recognitionRunning) {
        return;
    }

    const cooldownDelay = Math.max(0, speechCooldownUntil - Date.now());
    const waitTime = Math.max(delay, cooldownDelay);

    if (recognitionRestartTimer) {
        clearTimeout(recognitionRestartTimer);
    }

    recognitionRestartTimer = setTimeout(() => {
        recognitionRestartTimer = null;
        if (!recognition || manualStop || !listening || recognitionRunning) {
            return;
        }
        try {
            recognition.lang = currentLanguage === "hi" ? "hi-IN" : "en-US";
            recognition.start();
            recognitionRunning = true;
            updateMicUi(true);
        } catch (error) {
            updateMicUi(false);
        }
    }, waitTime);
}

function refreshVoices() {
    if (!("speechSynthesis" in window)) {
        return;
    }
    availableVoices = window.speechSynthesis.getVoices() || [];
}

function pickVoice(lang) {
    const voices = availableVoices.length ? availableVoices : (window.speechSynthesis.getVoices() || []);
    const targetLang = lang === "hi" ? "hi-IN" : "en-US";
    const preferred = voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith(targetLang.toLowerCase()));
    if (preferred) {
        return preferred;
    }
    if (lang === "hi") {
        return voices.find((voice) => /hindi|india/i.test(voice.name || "")) || null;
    }
    return (
        voices.find((voice) => /zira|female|woman|girl/i.test(voice.name || "")) ||
        voices.find((voice) => /natural|online|google/i.test(voice.name || "")) ||
        voices[0] ||
        null
    );
}

if ("speechSynthesis" in window) {
    refreshVoices();
    window.speechSynthesis.addEventListener("voiceschanged", refreshVoices);
}

function addBubble(text, role) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    bubble.textContent = text;
    conversation.appendChild(bubble);
    conversation.scrollTop = conversation.scrollHeight;
}

function setStatus(text) {
    statusEl.textContent = text;
    const value = String(text || "").toLowerCase();
    const state = value.includes("listening")
        ? "listening"
        : value.includes("speaking")
            ? "speaking"
            : value.includes("thinking")
                ? "thinking"
                : value.includes("waiting")
                    ? "waiting"
                    : value.includes("session ended")
                        ? "session"
                        : value.includes("error") || value.includes("could not")
                            ? "error"
                            : "ready";

    if (statusBadge) {
        statusBadge.className = "status-badge";
    }
    if (speechIcon) {
        speechIcon.className = "speech-icon";
    }
    if (speechWaveform) {
        speechWaveform.className = "speech-waveform";
    }

    if (!statusBadge && !speechIcon) {
        return;
    }

    if (value.includes("listening")) {
        statusBadge?.classList.add("status-listening");
        statusBadge && (statusBadge.textContent = "Listening");
        speechIcon?.classList.add("speech-listening");
        speechWaveform?.classList.add("speech-listening");
    } else if (value.includes("speaking")) {
        statusBadge?.classList.add("status-speaking");
        statusBadge && (statusBadge.textContent = "Speaking");
        speechIcon?.classList.add("speech-speaking");
        speechWaveform?.classList.add("speech-speaking");
    } else if (value.includes("thinking")) {
        statusBadge?.classList.add("status-thinking");
        statusBadge && (statusBadge.textContent = "Thinking");
        speechIcon?.classList.add("speech-thinking");
        speechWaveform?.classList.add("speech-thinking");
    } else if (value.includes("waiting")) {
        statusBadge?.classList.add("status-waiting");
        statusBadge && (statusBadge.textContent = "Waiting");
        speechIcon?.classList.add("speech-waiting");
        speechWaveform?.classList.add("speech-waiting");
    } else if (value.includes("session ended")) {
        statusBadge?.classList.add("status-session");
        statusBadge && (statusBadge.textContent = "Stopped");
        speechIcon?.classList.add("speech-session");
        speechWaveform?.classList.add("speech-session");
    } else if (value.includes("error") || value.includes("could not")) {
        statusBadge?.classList.add("status-error");
        statusBadge && (statusBadge.textContent = "Error");
        speechIcon?.classList.add("speech-error");
        speechWaveform?.classList.add("speech-error");
    } else {
        statusBadge?.classList.add("status-ready");
        statusBadge && (statusBadge.textContent = "Ready");
        speechIcon?.classList.add("speech-ready");
        speechWaveform?.classList.add("speech-ready");
    }
}

function speak(text, lang = "en") {
    return new Promise((resolve) => {
        if (!("speechSynthesis" in window)) {
            resolve();
            return;
        }

        if (recognition && listening && !manualStop) {
            speechPaused = true;
            speechResumeNeeded = true;
            ignoreRecognitionUntil = Date.now() + 1400;
            speechCooldownUntil = Math.max(speechCooldownUntil, ignoreRecognitionUntil);
            try {
                recognition.abort();
            } catch (error) {
                try {
                    recognition.stop();
                } catch (innerError) {
                    speechPaused = false;
                }
            }
        }

        setStatus("Speaking...");
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = lang === "hi" ? "hi-IN" : "en-US";
        utterance.rate = lang === "hi" ? 0.92 : 0.98;
        utterance.pitch = lang === "hi" ? 1.02 : 0.96;
        utterance.volume = 1.0;
        const voice = pickVoice(lang);
        if (voice) {
            utterance.voice = voice;
        }
        utterance.onend = () => {
            resolve();
            speechCooldownUntil = Math.max(speechCooldownUntil, Date.now() + 900);
            if (speechResumeNeeded && !manualStop) {
                speechPaused = false;
                speechResumeNeeded = false;
                setStatus("Listening...");
                startListeningSoon(550);
            } else if (!manualStop && listening) {
                setStatus("Listening...");
            }
        };
        utterance.onerror = () => {
            speechPaused = false;
            speechResumeNeeded = false;
            if (!manualStop && listening) {
                setStatus("Listening...");
            }
            resolve();
        };
        window.speechSynthesis.speak(utterance);
    });
}

function handleAction(data) {
    if (!data || !data.action) {
        return;
    }

    if (data.action === "open_url" && data.data && data.data.url) {
        const url = data.data.url;
        if (url.startsWith("tel:") || url.startsWith("sms:") || url.startsWith("mailto:")) {
            window.location.href = url;
            return;
        }
        window.open(url, "_blank", "noopener");
        return;
    }

    if (data.action === "scroll_page") {
        const direction = data.data && data.data.direction ? data.data.direction : "down";
        const amount = data.data && data.data.amount ? Number.parseInt(data.data.amount, 10) : 5;
        const distance = Number.isFinite(amount) ? Math.max(1, amount) * 220 : 1100;
        window.scrollBy({
            top: direction === "up" ? -distance : distance,
            behavior: "smooth",
        });
        return;
    }

    if (data.action === "move_mouse" || data.action === "mouse_click") {
        setStatus("That action works on the desktop host, not inside the browser tab.");
    }
}

async function sendCommand(command) {
    if (!command.trim()) {
        return;
    }

    addBubble(command, "user");
    setStatus("Thinking...");

    try {
        const response = await fetch("/api/command", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ command }),
        });

        const raw = await response.text();
        let data = {};
        if (raw) {
            try {
                data = JSON.parse(raw);
            } catch (parseError) {
                data = response.ok ? { message: raw } : {};
            }
        }

        if (!response.ok) {
            const serverMessage = data && data.message ? data.message : `The assistant server returned ${response.status}.`;
            data = { ...data, message: serverMessage, should_exit: false, needs_confirmation: false, action: "", data: {}, announcements: [] };
        }

        currentLanguage = data.language || currentLanguage;
        handleAction(data);

        if (Array.isArray(data.announcements)) {
            for (const announcement of data.announcements) {
                if (!announcement) {
                    continue;
                }
                addBubble(announcement, "assistant");
                await speak(announcement, currentLanguage);
            }
        }

        if (data.message) {
            addBubble(data.message, "assistant");
            await speak(data.message, currentLanguage);
        }

        if (recognition) {
            recognition.lang = currentLanguage === "hi" ? "hi-IN" : "en-US";
        }

        if (data.needs_confirmation) {
            setStatus("Waiting for confirmation.");
        } else if (data.should_exit) {
            setStatus("Session ended.");
            manualStop = true;
            autoRestart = false;
            speechPaused = false;
            speechResumeNeeded = false;
            if (recognition && listening) {
                recognition.stop();
            }
        } else {
            if (!manualStop && listening) {
                startListeningSoon(75);
            }
        }
    } catch (error) {
        console.error("Command request failed:", error);
        addBubble("Sorry, I could not reach the assistant server just now.", "assistant");
        setStatus("Error.");
        if (!manualStop && listening) {
            startListeningSoon(300);
        }
    }
}

function queueCommand(command) {
    input.value = command;
    input.focus();
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const command = input.value;
    input.value = "";
    await sendCommand(command);
});

quickCommands.forEach((button) => {
    button.addEventListener("click", async () => {
        const command = button.dataset.command || "";
        if (!command) {
            return;
        }
        queueCommand(command);
        await sendCommand(command);
        input.focus();
    });
});

micBtn.addEventListener("click", () => {
    if (!Recognition) {
        setStatus("Speech recognition is not available in this browser.");
        return;
    }

    if (!recognition) {
        recognition = new Recognition();
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;
        recognition.lang = currentLanguage === "hi" ? "hi-IN" : "en-US";

        recognition.onresult = async (event) => {
            const transcript = event.results[0][0].transcript;
            if (Date.now() < ignoreRecognitionUntil) {
                return;
            }
            await sendCommand(transcript);
        };

        recognition.onerror = () => {
            setStatus("Mic error. Try again.");
        };

        recognition.onend = () => {
            recognitionRunning = false;
            if (manualStop) {
                autoRestart = false;
                updateMicUi(false);
                return;
            }

            if (speechPaused) {
                speechPaused = false;
                speechResumeNeeded = false;
                startListeningSoon(650);
                return;
            }

            if (autoRestart) {
                startListeningSoon();
                return;
            }

            if (listening) {
                startListeningSoon();
                return;
            }

            updateMicUi(false);
        };
    }

    if (listening) {
        manualStop = false;
        autoRestart = false;
        speechPaused = false;
        speechResumeNeeded = false;
        ignoreRecognitionUntil = 0;
        speechCooldownUntil = 0;
        recognition.stop();
        recognitionRunning = false;
        updateMicUi(false);
        return;
    }

    manualStop = false;
    autoRestart = true;
    ignoreRecognitionUntil = 0;
    speechCooldownUntil = 0;
    recognition.lang = currentLanguage === "hi" ? "hi-IN" : "en-US";
    recognition.start();
    recognitionRunning = true;
    updateMicUi(true);
});

stopBtn.addEventListener("click", () => {
    manualStop = true;
    autoRestart = false;
    speechPaused = false;
    speechResumeNeeded = false;
    ignoreRecognitionUntil = 0;
    speechCooldownUntil = 0;
    if (recognitionRestartTimer) {
        clearTimeout(recognitionRestartTimer);
        recognitionRestartTimer = null;
    }
    if (recognition && listening) {
        recognition.stop();
    }
    recognitionRunning = false;
    updateMicUi(false);
});

addBubble("Try the quick-start chips above, or say help for the full command guide.", "assistant");
setStatus("Ready.");
