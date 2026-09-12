"""
Deterministic rules for the onboarding flow. No LLM involvement here on
purpose -- track assignment and state transitions must be reproducible
and testable, per the scenario's success criteria.
"""

from enum import Enum


class State(str, Enum):
    PROFILE_IN_PROGRESS = "PROFILE_IN_PROGRESS"
    TRACK_SELECTED = "TRACK_SELECTED"
    LEARNING = "LEARNING"
    LAB_UNLOCKED = "LAB_UNLOCKED"
    LAB_COMPLETE = "LAB_COMPLETE"
    PROJECT_SELECTED = "PROJECT_SELECTED"
    COMMUNITY_HANDOFF_PENDING = "COMMUNITY_HANDOFF_PENDING"


# Weekly-hours option -> numeric midpoint used for storage/reporting.
HOURS_MAP = {
    "1-2 hours": 1.5,
    "2-4 hours": 3,
    "5-8 hours": 6.5,
    "8+ hours": 10,
}

# Programming background option -> normalized level.
PROGRAMMING_LEVEL_MAP = {
    "Python / JavaScript / Java": "basic_software",
    "C / C++": "systems_software",
    "None": "none",
}

HARDWARE_MAP = {
    "No previous experience": "none",
    "Some (Arduino, breadboards, etc.)": "some",
    "Formal EE/CE background": "experienced",
}


def determine_track(programming_level: str, hardware_experience: str) -> str:
    """
    Deterministic mapping from background to track. Extend this table --
    do not replace it with an LLM call -- if new tracks are added.
    """
    if hardware_experience == "none" and programming_level in ("basic_software", "none"):
        return "software_to_riscv"
    if hardware_experience == "none" and programming_level == "systems_software":
        return "systems_to_riscv"
    if hardware_experience in ("some", "experienced"):
        return "hardware_to_riscv"
    return "software_to_riscv"  # safe default