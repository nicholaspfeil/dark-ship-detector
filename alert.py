"""
alert.py — Milestone 5: say the alert out loud, without anyone looking at a screen.

1. First choice: Twilio phones the dispatcher and reads the alert aloud.
   We hand Twilio a tiny *TwiML* document (Twilio's XML instructions for a
   call); <Say> means "read this text with a computer voice".
2. Fallback: if Twilio isn't set up, the call fails, or nobody picks up, the
   laptop speaks the alert through its own speakers (Windows' built-in voice).

The call runs in a background thread so the detector keeps watching ships
while the phone rings.

Try it:
    python alert.py --speaker            # laptop voice only (no call)
    python alert.py                      # real call to MY_PHONE_NUMBER (fallback to speaker)
    python alert.py --text "Test alert."
"""

import argparse
import os
import subprocess
import threading
import time
from xml.sax.saxutils import escape

from secrets_env import get_secret

VOICE = "Polly.Joanna"  # a natural-sounding Amazon voice that Twilio offers
# Call states that mean "the dispatcher did not hear it" -> use the fallback.
FAILED_STATES = {"failed", "busy", "no-answer", "canceled"}
STATUS_WAIT_S = 45  # how long to watch the call before giving up on it


def twiml_for(text):
    """Build the call's script: say the alert, pause, then repeat it once."""
    t = escape(text)  # turn &, <, > into XML-safe codes so the TwiML stays valid
    return (f'<Response><Say voice="{VOICE}">{t}</Say><Pause length="1"/>'
            f'<Say voice="{VOICE}">Repeating. {t}</Say></Response>')


def speak_local(text):
    """Read the text through the laptop speakers with Windows' built-in speech."""
    print(f"[alert] speaking on laptop: {text}")
    if os.name != "nt":
        print("[alert] (laptop speech only implemented for Windows)")
        return
    # The text goes in through an environment variable, so quotes or
    # apostrophes in ship names can't break the PowerShell command.
    script = ("Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$s.Rate = 0; $s.Speak($env:ALERT_TEXT)")
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   env={**os.environ, "ALERT_TEXT": text})


def twilio_ready():
    names = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "MY_PHONE_NUMBER")
    return all(get_secret(n, required=False) for n in names)


def call_phone(text):
    """
    Phone the dispatcher and read the alert. Returns True if the call was
    answered (or still going), False if it failed and we should fall back.
    """
    from twilio.rest import Client  # imported here so speaker-only mode needs no Twilio

    client = Client(get_secret("TWILIO_ACCOUNT_SID"), get_secret("TWILIO_AUTH_TOKEN"))
    call = client.calls.create(twiml=twiml_for(text),
                               to=get_secret("MY_PHONE_NUMBER"),
                               from_=get_secret("TWILIO_FROM_NUMBER"))
    print(f"[alert] calling dispatcher (call {call.sid})")

    # Twilio places the call on its side; watch its status to learn whether
    # it actually rang and was answered.
    deadline = time.time() + STATUS_WAIT_S
    status = call.status
    while time.time() < deadline:
        status = client.calls(call.sid).fetch().status
        if status in FAILED_STATES:
            print(f"[alert] call {status}")
            return False
        if status in ("in-progress", "completed"):
            print(f"[alert] call answered ({status})")
            return True
        time.sleep(2)
    print(f"[alert] call still '{status}' after {STATUS_WAIT_S}s")
    return status not in ("queued", "initiated", "ringing")


def send_alert(text, use_phone=True):
    """Phone first, laptop speaker if that's off or fails. Blocks until done."""
    if use_phone and twilio_ready():
        try:
            if call_phone(text):
                return "phone"
        except Exception as e:  # bad credentials, no internet, Twilio error...
            print(f"[alert] phone call failed ({type(e).__name__}: {e})")
    elif use_phone:
        print("[alert] Twilio not configured; using laptop speaker")
    speak_local(text)
    return "speaker"


def send_alert_async(text, use_phone=True):
    """Same as send_alert, but in a background thread so detection keeps running.
    Not a daemon thread: the program waits for the alert to finish before exiting."""
    t = threading.Thread(target=send_alert, args=(text, use_phone))
    t.start()
    return t


def main():
    parser = argparse.ArgumentParser(description="Send a test alert.")
    parser.add_argument("--text", default="Alert. This is a test of the Dark Ship Detector. Risk score 85 out of 100.")
    parser.add_argument("--speaker", action="store_true", help="laptop speaker only, no phone call")
    args = parser.parse_args()
    print(f"[alert] delivered by: {send_alert(args.text, use_phone=not args.speaker)}")


if __name__ == "__main__":
    main()
