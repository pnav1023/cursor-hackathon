FRESH PDF READY, open on your screen now: ~/Downloads/referral-11-Elena-Whitfield.pdf
New patient Elena HACKDEMO-Whitfield (DOB 06/14/1979), URGENT cardiology referral, Aekna insurance. She's not on the demo copy, so the run is clean. I checked that our reader pulls every field correctly (13 of 13).
Walkthrough: open http://localhost:4710/ (blank) → URL https://demo.openemr.io/a/openemr → Upload documents: that PDF → Run it → log in (admin / pass) in the pop-up.

WHAT TO CALL OUT, IN ORDER
1. THE PROBLEM (before touching anything, ~20 s)
"Front desks get referral faxes all day. Mary retypes each one into the health-records system: patient, insurance, attach the fax, book the visit. About 3–4 minutes each, error-prone, and her software has no API she can use. So nobody automates it."
2. THE IDEA
"Mary shows the workflow once. We turn it into a tested tool her own AI can run, and every step is proven, not just claimed."
3. THE FORM: "any tool, any documents"
Point at: her tool's URL, how she shows the workflow (screen recording or Chrome recording), her goal in her own words, and the documents to process. Upload Elena's fax.
4. LOGIN: the trust moment
"Mary logs in herself in a real window. We never see or store her password; only the session is kept, and if it expires, this window pops back up and the work continues."
5. THE RUN: the wow
Watch the visible browser: patient created → insurance typed from the fax → the fax attached to the chart → New Patient visit booked. Point at the step rail on the right turning green.
Say: "After EVERY save it re-opens the record and checks it. Browser agents say 'done'. We show proof."
6. TRIAGE: the non-obvious insight
Elena is URGENT, so she's booked first. On a batch it also holds a duplicate patient, a missing member ID and a wrong-format member ID for Mary: "it asks instead of guessing."
7. THE REVIEW: Mary stays in control
Open the review card: the fax fields next to what OpenEMR saved, all ✓. Click the patient chart link to open the real record. Click "Looks right".
8. TAKE IT WITH YOU
"Download the skill": Mary drops it into her own AI (Cursor/Claude) and can say "process this morning's faxes". Her AI shows a dry-run plan and asks before writing.
9. PROOF + SO WHAT (close)
"Tested on 10 of 10 referrals, 41 of 41 steps confirmed; about 1.5 min each hands-free vs 3–4 min by hand (our estimate). No API keys; open-source health-records demo; fictional patients. Next: learn any app from a recording, and AI reading for any document layout."

HONEST LINES TO KEEP: say "this app / these referral faxes" rather than "any app today". Step 1 on the page uses our saved workflow for this app when only a video is uploaded; it doesn't claim to have analysed the video.
