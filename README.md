# RISC-V Onboarding Bot

A Discord onboarding assistant for a RISC-V learning community. New members run a guided `/start` flow that assesses their background, assigns them a learning track, walks them through a lesson and quiz, verifies a hands-on lab exercise using a real RISC-V simulator, recommends a project, and hands them off to the community with an explicit, confirm-before-posting introduction.

The bot is split into two layers:

- **A deterministic core** — state machine, content, and grading are all fixed and reviewed. No LLM is involved in quiz grading, track assignment, or lab verification.
- **An optional conversational layer** — a free-form Q&A agent (DM or `@mention` only) that can explain concepts and draft a community intro, but cannot grade anything, change a user's state, or post to a channel on its own.

## Want to try it?

The Discord server is invite-only. Email **hmu026@icloud.com** to request access.

## Architecture

| File | Responsibility |
|---|---|
| `bot.py` | Entry point. Registers `/start`, drives the persisted state machine via Discord buttons/selects/modals. |
| `db.py` | SQLite persistence for user state/profile (so a user can resume after a bot restart) and a separate, never-publicly-referenced misconception table. |
| `state_machine.py` | Pure, deterministic rules — no LLM — for mapping a user's background to a learning track. |
| `content_bank.py` | Loads reviewed lesson/quiz/lab/project content from `content/*.json`. Nothing here is generated live. |
| `emulator.py` | Shells out to [RARS](https://github.com/TheThirdOne/rars) (a real RISC-V simulator, run via Java) to execute lab submissions and read back register values. |
| `agent.py` | Optional conversational layer for free-form Q&A, adaptive explanations, and community-intro drafting. Tool access is read-only over content/state, plus one draft-only tool for proposing an intro. |

### State machine

```
PROFILE_IN_PROGRESS → TRACK_SELECTED → LEARNING → LAB_UNLOCKED
    → LAB_COMPLETE → PROJECT_SELECTED → COMMUNITY_HANDOFF_PENDING
```

Each state is persisted in SQLite, so restarting the bot mid-flow resumes a user exactly where they left off (see `resume()` in `bot.py`).

### Content bank

`content_bank.py` reads four reviewed JSON files from a `content/` directory at the project root:

```
content/
├── lessons.json    # {track: {title, body}}
├── quiz.json       # {track: [{id, prompt, code, options, correct_option, misconception_tags, explanation}]}
├── labs.json       # {track: {id, starter_code, goal_text, target_register, target_value}}
└── projects.json   # [{id, title, reviewed, tracks, description, estimated_time, first_task, definition_of_done, recommended_channel}]
```

Every track currently in use (`software_to_riscv`, `systems_to_riscv`, `hardware_to_riscv`) needs an entry in `lessons.json`, `quiz.json`, and `labs.json`, or that step of the flow will silently degrade (an empty quiz skips straight to the lab) or fail outright (a missing lesson/lab throws).

### The agent's boundaries

`agent.py` only fires on a DM or an `@mention` — plain channel messages are ignored by design. Its tool set is deliberately limited:

- Read-only tools for the user's profile, current lesson, current quiz question (never the correct answer), current lab, and the reviewed project catalog.
- One draft-only tool, `propose_community_intro`, which returns a drafted string. `bot.py` is responsible for stashing that draft and showing the same confirm/decline UI (`CommunityHandoffView`) used everywhere else — the agent has no tool that can post to a channel or advance a user's state.

## Setup

1. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

2. **Configure environment variables.** Copy `.env.example` to `.env` and fill in:

   | Variable | Purpose |
   |---|---|
   | `DISCORD_TOKEN` | Your bot's token from the Discord Developer Portal. |
   | `GUILD_ID` | Your server's ID — enables instant guild-scoped slash command sync during testing. |
   | `RARS_JAR_PATH` | Path to a downloaded `rars.jar` (see below). |
   | `HF_TOKEN` | Hugging Face token, used by `agent.py`'s OpenAI-compatible client. |
   | `HF_MODEL` | Model to use on Hugging Face's router (defaults to `Qwen/Qwen3-8B`). |

3. **Set up Discord Developer Portal permissions.**
   - Under **Bot → Privileged Gateway Intents**, enable **Message Content Intent** (required for the agent's DM/@mention Q&A).
   - Under **OAuth2 → URL Generator**, select both the `bot` and `applications.commands` scopes, choose the bot permissions it needs (Send Messages, View Channels, Embed Links, Attach Files, etc.), and use the generated URL to invite the bot to your server. Both scopes are required — `applications.commands` alone can register commands but won't let the bot act as a member of the guild, and `bot` alone won't let you sync slash commands.

4. **Download and place the RARS simulator jar**, then point `RARS_JAR_PATH` at it:
   ```
   https://github.com/TheThirdOne/rars/releases/download/v1.6/rars1_6.jar
   ```
   Confirm your setup with `java -jar <path> h` — flags used by `emulator.py` (`sm`, `nc`, `dec`, `ae1`, `se2`, plus register names) are verified against RARS 1.6; a future RARS release could rename or drop them.

5. **Populate `content/`** with reviewed lessons, quiz questions, labs, and projects for each track (see Content bank above).

6. **Run the bot**
   ```
   python bot.py
   ```

## Mapping the onboarding scenario to files

| Step | Files involved |
|---|---|
| `/start`, profile intake, track assignment | `bot.py` (`GoalView`, `ProgrammingBackgroundView`, `HardwareBackgroundView`, `WeeklyHoursView`), `state_machine.py` |
| Lesson delivery | `bot.py` (`send_lesson`), `content_bank.py`, `content/lessons.json` |
| Quiz + misconception tracking | `bot.py` (`QuizView`, `send_quiz`), `content/quiz.json`, `db.py` (misconception table) |
| Lab submission + emulator verification | `bot.py` (`LabSubmitModal`, `send_lab`), `emulator.py`, `content/labs.json` |
| Project recommendation | `bot.py` (`ProjectSelectView`, `send_project_recommendations`), `content/projects.json` |
| Community handoff (confirm-before-post) | `bot.py` (`CommunityHandoffView`, `send_completion`), `db.py` (`stash_confirmation` / `clear_confirmation`) |
| Free-form Q&A, adaptive explanations, intro drafting | `agent.py` |
| Persisted state / resume-after-restart | `db.py` |

## A note on the misconception table

Misconceptions recorded during the quiz are stored in a separate table in `db.py` and are never surfaced publicly, referenced in the community intro draft, or exposed through any of `agent.py`'s tools — they exist solely to let the bot recognize when a user has resolved a prior wrong answer.