## Coding and Agentic Engineering

- **A green suite can stay green after the check is reversed. The verifier has to mutate the behavior and see red.** (@NatureBlueee, 2026-10-27, search) https://x.com/NatureBlueee/status/2115186551407944177
> All 12 tests passed. An independent verifier reversed the condition to count finished tasks instead. All 12 still passed.
> One verifier reported five deliberately broken changes that left all 1,621 relevant tests green.

- **The agent must run the project tests at commit time, because a prompt is not enough.** (@wmertens, 2026-10-28, search) https://x.com/wmertens/status/2115473040624554360
> A nice trick is e.g. to use a precommit hook to require an agent to run tests before committing. Sometimes it might forget but not if it gets the message at commit time

- **Do not merge an agent patch until the tests pass on the commit that will actually land.** (@DYoung_AI, 2026-10-28, search) https://x.com/DYoung_AI/status/2115470900808102089
> Concrete default: no merge of agent patches until upstream is green AND patch tests pass on the rebased tip.

## Repeated asks

Run the suite outside the model, and do not treat a green result as proof.

- https://x.com/NatureBlueee/status/2115186551407944177
- https://x.com/wmertens/status/2115473040624554360
- https://x.com/DYoung_AI/status/2115470900808102089
