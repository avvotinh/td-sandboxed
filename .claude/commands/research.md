Research a topic before implementing. Spawns the `researcher` agent which searches GitHub, Context7, and the web for existing solutions, then writes findings to `docs/research/<slug>-<date>.md`.

Usage: `/research <topic>`

Examples:
- `/research trailing drawdown rule for FTMO`
- `/research python TA indicator library comparison`
- `/research ZeroMQ CURVE auth setup`

Steps:
1. If `$ARGUMENTS` is empty, ask the user what topic to research and stop.
2. Check `docs/research/` for an existing file on this topic — if found, show the path and ask whether to refresh or skip.
3. Delegate to the `researcher` subagent with the topic as the prompt. Tell it: "Research this for the Sandboxed project and write output to `docs/research/<slug>-<today>.md` following your template. Return the file path and a 3-sentence TL;DR."
4. After the agent returns, print the file path and the TL;DR so the user can decide whether to feed it into `planner` / `architect`.
