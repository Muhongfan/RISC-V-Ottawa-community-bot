"""
Loads reviewed content. The bot NEVER generates lesson text, quiz answers,
or project recommendations via an LLM -- it only selects from these
reviewed files, per the scenario's success criteria.
"""

import json
import os

CONTENT_DIR = os.path.join(os.path.dirname(__file__), "content")


def _load(filename):
    with open(os.path.join(CONTENT_DIR, filename)) as f:
        return json.load(f)


def get_lesson(track: str):
    return _load("lessons.json").get(track)


def get_quiz(track: str):
    return _load("quiz.json").get(track, [])


def get_lab(track: str):
    return _load("labs.json").get(track)


def get_reviewed_projects(track: str):
    all_projects = _load("projects.json")
    return [p for p in all_projects if p.get("reviewed") and track in p.get("tracks", [])]