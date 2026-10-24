# Pitch: Dark Ship Detector (2 minutes)

## Before you start
- Phone on the table, volume up, ringer ON.
- Terminal open in the repo, font large. Command typed but not run: `.venv\Scripts\python demo.py --dashboard`
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
