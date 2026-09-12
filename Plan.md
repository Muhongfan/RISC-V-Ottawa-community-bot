# Alex — Software Beginner End-to-End Scenario

## Purpose

Verify whether a software student with no hardware background can complete their first RISC-V hands-on exercise and select a community project entirely through Discord.

## User Profile

* Name: Alex
* Programming: Python
* Git experience: Basic
* C experience: None
* Assembly experience: None
* Hardware experience: None
* Hardware available: No
* Weekly availability: 3 hours
* Goal: Join a beginner-friendly RISC-V community project

## Preconditions

* Alex has joined the private Discord test server.
* The bot is online.
* The `/start` guild command is registered.
* Three starter projects have reviewed status.
* Alex has no existing learning profile.

## Happy Path

### Step 1 — Start

Alex enters:

```text
/start
```

The bot displays:

> What would make today feel successful?

Alex selects:

> Run my first RISC-V program

Expected state:

```text
PROFILE_IN_PROGRESS
```

### Step 2 — Background

The bot asks about Alex’s programming background.

Alex selects:

> Python / JavaScript / Java

The bot asks about hardware or assembly experience.

Alex selects:

> No previous experience

The bot asks how much time Alex can spend each week.

Alex selects:

> 2–4 hours

Expected profile:

```json
{
  "goal": "run_first_program",
  "programming_level": "basic_software",
  "hardware_experience": "none",
  "weekly_hours": 3,
  "track": "software_to_riscv"
}
```

Expected state:

```text
TRACK_SELECTED
```

### Step 3 — First Lesson

The bot sends predefined learning content about the ISA and registers.

Alex answers the first set of questions.

Expected state:

```text
LEARNING
```

### Step 4 — Misconception

The bot asks:

> What is the value of t1 after executing these instructions?

```asm
li t0, 5
addi t1, t0, 3
```

Alex incorrectly selects:

> 3

Expected result:

* The bot does not deduct points.
* The bot records `immediate-is-final-result`.
* The bot explains the destination register, source register, and immediate value.
* The bot allows Alex to retry.
* Alex’s private misconception record is not posted to a public channel.

Alex selects the following answer on the second attempt:

> 8

Expected result:

* The answer is accepted.
* The misconception is marked as `repaired`.
* Alex unlocks the code experiment.

Expected state:

```text
LAB_UNLOCKED
```

### Step 5 — Discord Lab

The bot displays:

```asm
li t0, 4
addi t1, t0, 3
add t2, t0, t1
```

Goal:

> Make t2 finish at 15.

Alex changes `3` to `7` and submits the code.

Expected trace:

```text
t0: 0 → 4
t1: 0 → 11
t2: 0 → 15
```

Expected state:

```text
LAB_COMPLETE
```

### Step 6 — Project Recommendation

The bot recommends projects exclusively from reviewed entries in the Project Catalog.

Expected recommendations:

1. Register Trace Explainer
2. C-to-RISC-V Explorer
3. Instruction Decoder Visualizer

Alex selects:

> Register Trace Explainer

Expected state:

```text
PROJECT_SELECTED
```

### Step 7 — Completion

The bot displays:

* The project goal
* The estimated time required
* The first task
* The definition of done
* The recommended community channel
* A draft community introduction

The bot does not automatically post any content publicly.

Expected state:

```text
COMMUNITY_HANDOFF_PENDING
```

## End-to-End Success Criteria

* Alex can complete the core workflow without leaving Discord.
* Track selection follows deterministic rules.
* Correct answers are defined in reviewed content.
* Program results are verified by an emulator.
* Recommended projects come from reviewed entries in the Project Catalog.
* Alex’s private misconception records remain private.
* The community introduction is not sent without confirmation.
* Alex can resume the workflow after the bot restarts.
* The entire workflow can be completed within 20–30 minutes.
