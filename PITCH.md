# Pitch: Dark Ship Detector (2 minutes)

## 2-sentence summary (for the submission form)
Dark Ship Detector watches live ship-tracking (AIS) traffic off San Diego, learns what normal looks like, and scores every ship that goes silent by how suspicious the silence is: moving, deep inside receiver range, heading for the Cabrillo marine reserve, and so on. It turns ~490 silences a day into a handful of alerts and phones a dispatcher with a spoken alert and its reasons, so nobody has to watch a screen.

## 2-minute demo video script
Lead with the phone; the chart is supporting. Record the screen plus the phone on speaker (or film both).

| Time | Show | Say |
|---|---|---|
| 0:00-0:20 | Your face or the title chart | "Boats fishing illegally in marine reserves switch off their tracking transponder. But ships go silent all the time for harmless reasons, so an alarm on every silence gets ignored. We built something a dispatcher never has to look at." |
| 0:20-0:30 | Run `demo.py --dashboard`, sound on | "This is a real recording off San Diego from October 19, at 60x speed. The dispatcher never sees this screen. It's here so you can see what the system sees." |
| 0:30-0:55 | Ghosts appear, soft ticks play | "Each dot is a ship. When one goes silent, it becomes a ghost, and the circle shows where it could be by now. These ticks are silences it's ignoring: Navy tugs, boats docked in the bay. Risk 1." |
| 0:55-1:30 | Phone rings, put it on speaker, let it talk | *(Let the call play: Oceanus, 12 knots, 25 miles inside coverage, toward the Cabrillo reserve, risk 95, main reasons.)* |
| 1:30-1:50 | Alert card, then the impact panel | "That's the whole interface: one phone call, with the reasons. Across all our recordings, about 490 silences a day became 17 calls." |
| 1:50-2:00 | Repo link | "It runs live today on the free public feed. Dark Ship Detector." |

## Before you start
- Phone on the table, volume up, ringer ON.
- Terminal open in the repo, font large. Command typed but not run: `.venv\Scripts\python demo.py --dashboard --two-way` (press 1 on the call to send a patrol)
  (it opens the live chart in your browser by itself; put that window on the projector and press F11 for full screen).
- Click "Turn on sound" on the chart once it opens, so the room hears each silence as a tone.
- `map.html` open in another tab for the Q&A (run `python make_map.py` first).
- Plan B if the call fails: the laptop speaks the alert by itself, so keep talking.

## Script

**Problem (20 s)**
"Boats fishing illegally in marine reserves do one simple thing: they switch off their tracking transponder, called AIS. Right off Point Loma is the Cabrillo marine reserve, a no-take zone right next to the San Diego harbor entrance. The hard part isn't noticing silence. Ships go silent all the time. In our data, 77% of silences were boats parked inside a harbor, and about a quarter were Navy or government vessels. An alarm on every silence gets ignored within a day."

**What it does (15 s)**
"Dark Ship Detector watches live ship traffic off San Diego, learns what normal looks like, and when a ship goes quiet it scores how suspicious that is, with reasons. Then it does the one thing a dispatcher needs: it calls their phone and tells them. No screen."

**Demo (45 s)** *(run `demo.py --dashboard`)*
"This is a real recording from October 19, playing at 60x. Each dot is a ship. When one goes quiet it turns into a ghost, and the circle shows everywhere it could be by now. Those soft ticks you hear are silences it's ignoring: Navy tug, risk 1; boat docked in the bay, risk 1. Correctly."
*(Oceanus hits, phone rings, put it on speaker)*
"Oceanus: moving 12 knots, 25 miles inside receiver range where signals don't just fade, heading for the reserve. If it held course, it passed within half a mile of the reserve 11 minutes after going dark. Risk 95."

**Why it's smart (25 s)** *(point at the chart)*
"Two things it learns from data. First, where receiver coverage really ends, this dotted blue line. Ships fade out naturally past it, so we don't alarm there. Second, each ship's own reporting rhythm. And it knows the difference between the feed going down and a ship going dark."

**Impact (15 s)**
"Across our recordings: about 490 silences a day become about 17 calls at our default threshold, or about 2 a day if you only want the most urgent. Same pipeline runs live today with one flag."

## Numbers to know (all from our recordings)
| | |
|---|---|
| Recordings | 4 sessions, 13.9 h of real coverage (outages removed) |
| Silences | 282 total (about 488 per 24 h) |
| Calls at risk 70 / 80 / 90 | about 17 / 5 / 2 per 24 h |
| Silences in a harbor / government | 77% / 27% |
| Simulated dark ships caught (`evaluate.py`) | 74 / 80 (92%); these scenarios match what the rules target |
| Oceanus after reappearing | shortest path while dark ran through the reserve |
| Coverage edge offshore (learned) | 22-44 nm from Point Loma, depending on direction |
| Normal gap between reports | median ~2.7 min, 90% under 15 min |

## Likely judge questions

**"How do you know Oceanus was actually doing something illegal?"**
"We don't, and we don't claim to. It's a ranked lead with reasons, not an accusation. The dispatcher decides. That's why it says 'risk score', not a percentage."

**"How did you pick the weights?"**
"By hand, from patterns in the data: stopped boats, harbors and government vessels go quiet harmlessly; moving ships deep inside coverage don't. There's no labeled dataset of confirmed dark ships. With feedback from dispatchers we'd fit the weights to real outcomes."

**"Isn't 17 calls a day still a lot?"**
"The threshold is one setting. At 80 it's 5 a day, at 90 about 2. A real deployment would tune it with the agency. The point is going from about 490 to a handful."

**"Why a phone call instead of a dashboard?"**
"Dispatchers and patrol crews are on radios and phones, not watching maps. The theme is invisible interfaces: the right alert, spoken, at the right moment."

**"What's the business?"**
"Customers: state fish and wildlife enforcement, marine protected area managers, the Coast Guard, and NGOs that monitor reserves. It runs on the free public AIS feed, so the cost is a laptop and a phone line. Expand by adding more reserves, which is just a list of corners."

**"What happens if the feed goes down?"**
"It's built for that. If no ship at all reports for 5 minutes, that's the feed, not the ships, and that time doesn't count against anyone. Our recordings had outages up to 20 hours; without that rule every ship would look dark after each one."

**"Does it work live?"**
"Yes: `demo.py --mode live`. Same code path. Silences just take 15+ minutes to show up in real time, which is why the demo uses a recording."
