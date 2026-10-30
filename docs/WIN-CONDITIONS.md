Scoreboard: no prior winner list is published for this online event and the official gallery is unpublished; nearest proxy only, Berlin Builders & Brews on 2026-10-18 had 74 projects and Little Big Questions won, public usage unpublished, https://nebiusglobalaihackathon.devpost.com/project-gallery https://hackathons.techeurope.io/events/nebius-build-week-hackathon-in-partnership-with-nvidia
Bar to beat: same-event rivals as of 2026-10-30: Slopgate 14 proven fixes of 15 SWE-bench Lite instances for $1.16 (https://github.com/agno-nymous/slopgate), AegisPR evidence from one controlled PR (https://github.com/Hari-Aditya-003/AegisPR); papers Otter 31.4% and AssertFlip 43.6% fail-to-pass; four equally weighted criteria are implementation, design, impact, and idea quality, https://nebiusglobalaihackathon.devpost.com/rules
Asset we will own: a public Python bug-fix case with a Nemotron-generated regression test and receipt showing the issue-specific failure on the buggy base and a pass on the fixed patch
Off-platform buyer: Python maintainer reviewing an AI-generated bug fix
Single entry: Latch
Verb the brief names: "agents that write, run, and test code in Token Factory"
Our product performs that verb: yes. The fixture flow in latch/run.py calls Nemotron Lightning and Ultra through Token Factory. The real issue flow in latch/prove.py calls Nemotron Ultra, writes an issue-conditioned test, and runs it against both commit snapshots. The harness owns the verdict.
Metric plan: measured 2026-10-30 on Token Factory, 42 live runs: 10 of 21 real fixes proven, 0 of 9 wrong patches accepted, 0 of 12 gates opened on rejected Nemotron fixes, $2.22 total; checked in latch/runs/eval-summary-repair.json and live at https://latch-mauve.vercel.app/eval
Live by: 2026-10-30 09:00 PDT
Deviation from research: replace generic mutation repair with issue-anchored base/patch proof after finding direct prior art in Crucible and SWE-Mutation; Berlin Build Week is only a proxy because this event's gallery is unpublished. The local Claude Code stop-hook path was killed after a real CLI 403 prevented runtime verification.
Ask it answers: https://x.com/NatureBlueee/status/2115186551407944177
Users who want it: https://x.com/NatureBlueee/status/2115186551407944177 https://x.com/wmertens/status/2115473040624554360 https://x.com/DYoung_AI/status/2115470900808102089
