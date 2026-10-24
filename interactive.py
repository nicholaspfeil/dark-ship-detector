"""
interactive.py — #4: a two-way call. The dispatcher answers with the keypad.

    "...Risk score 95 out of 100. Press 1 to send a patrol. Press 2 to dismiss.
     Press 3 to hear it again."

Normally Twilio needs a public web address to tell us which key was pressed,
and a laptop doesn't have one. Instead we use Twilio Studio: a call script
(a "flow") that runs on Twilio's own servers. We create the flow once through
the API, start it for each alert, then ASK Twilio afterwards which key was
pressed. No web server, no tunnel.

    python interactive.py --validate      # check the flow with Twilio, no call
    python interactive.py                 # real two-way test call
"""

import argparse
import json
import time

from secrets_env import get_secret

FLOW_NAME = "Dark Ship Detector alert"
VOICE = "Polly.Joanna"
WAIT_S = 150  # how long to wait for the dispatcher's answer
DECISIONS = {"1": "patrol", "2": "dismiss"}


def _say(name, text, nxt=None):
    step = {"event": "audioComplete", **({"next": nxt} if nxt else {})}  # no "next" = end of call
    return {"name": name, "type": "say-play", "transitions": [step],
            "properties": {"say": text, "voice": VOICE, "loop": 1, "offset": {"x": 0, "y": 0}}}


def flow_definition():
    """The call script, as Studio's JSON format: call -> menu -> branch on key."""
    menu = ("{{flow.data.alert}} Press 1 to send a patrol. Press 2 to dismiss. "
            "Press 3 to hear it again.")
    states = [
        {"name": "Trigger", "type": "trigger", "properties": {"offset": {"x": 0, "y": 0}},
         "transitions": [{"event": "incomingMessage"}, {"event": "incomingCall"},
                         {"event": "incomingRequest", "next": "call"}]},
        {"name": "call", "type": "make-outgoing-call-v2",
         "properties": {"from": "{{flow.channel.address}}", "to": "{{contact.channel.address}}",
                        "timeout": 40, "record": False, "offset": {"x": 0, "y": 0}},
         "transitions": [{"event": "answered", "next": "menu"}, {"event": "busy"},
                         {"event": "noAnswer"}, {"event": "failed"}]},
        {"name": "menu", "type": "gather-input-on-call",
         "properties": {"say": menu, "voice": VOICE, "number_of_digits": 1, "stop_gather": True,
                        "timeout": 8, "loop": 1, "offset": {"x": 0, "y": 0}},
         "transitions": [{"event": "keypress", "next": "choice"}, {"event": "speech"},
                         {"event": "timeout", "next": "no_answer"}]},
        {"name": "choice", "type": "split-based-on",
         "properties": {"input": "{{widgets.menu.Digits}}", "offset": {"x": 0, "y": 0}},
         "transitions": [
             {"event": "noMatch", "next": "menu"},
             {"event": "match", "next": "patrol", "conditions": [
                 {"friendly_name": "1", "arguments": ["{{widgets.menu.Digits}}"], "type": "equal_to", "value": "1"}]},
             {"event": "match", "next": "dismiss", "conditions": [
                 {"friendly_name": "2", "arguments": ["{{widgets.menu.Digits}}"], "type": "equal_to", "value": "2"}]},
         ]},
        _say("patrol", "Patrol requested. The alert is logged. Goodbye."),
        _say("dismiss", "Alert dismissed and logged. Goodbye."),
        _say("no_answer", "No choice made. The alert stays open. Goodbye."),
    ]
    return {"description": "Dark Ship Detector two-way alert", "states": states,
            "initial_state": "Trigger", "flags": {"allow_concurrent_calls": True}}


def _client():
    from twilio.rest import Client
    return Client(get_secret("TWILIO_ACCOUNT_SID"), get_secret("TWILIO_AUTH_TOKEN"))


def validate():
    """Ask Twilio whether the flow definition is valid, without creating anything."""
    r = _client().studio.v2.flow_validate.update(
        friendly_name=FLOW_NAME, status="published", definition=flow_definition())
    return r.valid


def ensure_flow(client):
    """Create the flow the first time; afterwards update it in place. Returns its ID."""
    for f in client.studio.v2.flows.list(limit=50):
        if f.friendly_name == FLOW_NAME:
            client.studio.v2.flows(f.sid).update(status="published", definition=flow_definition())
            return f.sid
    return client.studio.v2.flows.create(friendly_name=FLOW_NAME, status="published",
                                         definition=flow_definition()).sid


def interactive_call(text):
    """Phone the dispatcher with a keypad menu. Returns 'patrol', 'dismiss',
    'no choice', or 'not answered'."""
    client = _client()
    flow = ensure_flow(client)
    ex = client.studio.v2.flows(flow).executions.create(
        to=get_secret("MY_PHONE_NUMBER"), from_=get_secret("TWILIO_FROM_NUMBER"),
        parameters={"alert": text})
    print(f"[two-way] calling dispatcher (execution {ex.sid})")
    deadline = time.time() + WAIT_S
    while time.time() < deadline:
        time.sleep(3)
        ctx = client.studio.v2.flows(flow).executions(ex.sid).execution_context().fetch().context
        widgets = ctx.get("widgets", {})
        digits = str(widgets.get("menu", {}).get("Digits", ""))
        if digits in DECISIONS:
            return DECISIONS[digits]
        if client.studio.v2.flows(flow).executions(ex.sid).fetch().status == "ended":
            return "no choice" if "menu" in widgets else "not answered"
    return "no choice"


def main():
    parser = argparse.ArgumentParser(description="Two-way keypad alert call.")
    parser.add_argument("--validate", action="store_true", help="only check the flow with Twilio")
    parser.add_argument("--text", default="Alert. This is a test of the Dark Ship Detector two-way call.")
    args = parser.parse_args()
    if args.validate:
        print("flow valid:", validate())
        return
    print("dispatcher chose:", interactive_call(args.text))


if __name__ == "__main__":
    main()
