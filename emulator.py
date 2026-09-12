"""
Shells out to RARS (https://github.com/TheThirdOne/rars) to actually execute
a RISC-V program and read back register values -- this is the "verified by
an emulator" requirement, not a guess by the LLM/bot.

RARS has a built-in flag for this: passing a register name on the command
line (e.g. `t0`) makes it print that register's value at the end of the
run, as `<name>\\t<value>`. This has been verified directly against RARS
1.6 (`java -jar rars.jar h` documents it under "<reg_name>").

Flags used, and why:
    sm   -- start execution at the global label `main`
    nc   -- suppress the copyright banner (keeps stdout clean)
    dec  -- print register values in decimal
    ae1  -- exit code 1 specifically on an assemble error
    se2  -- exit code 2 specifically on a simulation (runtime) error
    (register names) -- e.g. t0 t1 t2, printed at the end of the run

Verified against real RARS 1.6:
    - success:        exit code 0, stdout ends with "<reg>\\t<value>" lines
    - assemble error:  exit code 1, stdout contains the error message
    - runtime error:   exit code 2
    - infinite loop:   never returns -- handled via subprocess timeout

SETUP REQUIRED:
    1. Download rars.jar, e.g.:
       https://github.com/TheThirdOne/rars/releases/download/v1.6/rars1_6.jar
    2. Place it in your project and set RARS_JAR_PATH (see .env.example).
    3. Confirm with `java -jar <path> h` -- if a future RARS version drops
       or renames these flags, this module will need updating to match.
"""

import os
import re
import subprocess
import tempfile

RARS_JAR_PATH = os.getenv("RARS_JAR_PATH", "rars.jar")
TIMEOUT_SECONDS = 10

_REG_LINE_RE = re.compile(r"^(\w+)\t(-?\d+)$")


class EmulationError(Exception):
    pass


def _build_full_program(user_code: str) -> str:
    """Wrap user code in the .text/.globl/main scaffold RARS's `sm` flag expects."""
    lines = [".text", ".globl main", "main:"]
    for line in user_code.splitlines():
        stripped = line.rstrip()
        lines.append(stripped if stripped.startswith(" ") else f"    {stripped}")
    return "\n".join(lines) + "\n"


def run_and_read_registers(user_code: str, registers_to_print: list[str]) -> dict[str, int]:
    """
    Assembles and runs user_code via RARS, returning {register_name: value}
    for each register in registers_to_print.
    """
    full_program = _build_full_program(user_code)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".s", delete=False) as f:
        f.write(full_program)
        asm_path = f.name

    cmd = ["java", "-jar", RARS_JAR_PATH, "sm", "nc", "dec", "ae1", "se2"] + registers_to_print + [asm_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise EmulationError(
            "Could not find `java` or the RARS jar. Check RARS_JAR_PATH and that a JRE is installed."
        )
    except subprocess.TimeoutExpired:
        raise EmulationError("Program did not finish within the timeout (possible infinite loop).")
    finally:
        os.unlink(asm_path)

    if result.returncode == 1:
        raise EmulationError(f"Assemble error:\n{result.stdout.strip()}")
    if result.returncode == 2:
        raise EmulationError(f"Runtime error:\n{result.stdout.strip()}")
    if result.returncode != 0:
        raise EmulationError(f"RARS exited with code {result.returncode}:\n{result.stdout.strip()}")

    values = {}
    for line in result.stdout.splitlines():
        match = _REG_LINE_RE.match(line.strip())
        if match and match.group(1) in registers_to_print:
            values[match.group(1)] = int(match.group(2))

    missing = [r for r in registers_to_print if r not in values]
    if missing:
        raise EmulationError(
            f"Couldn't find value(s) for {missing} in RARS output:\n{result.stdout}"
        )

    return values