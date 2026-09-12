"""
Agentic layer on top of the deterministic state machine.

Boundaries (enforced by which tools exist, not just prompt wording):
- All content tools are READ-ONLY: they return reviewed lesson/quiz/lab/
  project data, never grade anything, never expose the quiz's correct
  answer, never invent a project outside the reviewed catalog.
- The only "write" tool is propose_community_intro, and even that doesn't
  post anything -- it just returns a drafted string. bot.py is responsible
  for stashing that draft and showing the existing confirm/decline UI
  (CommunityHandoffView). The agent has no tool that can post to a
  channel or advance a user's state.
"""

import os
import json
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv
import db
import content_bank


load_dotenv()
# Hugging Face Inference Providers expose an OpenAI-compatible chat
# completions endpoint, so we reuse the openai client -- just pointed at
# HF's router with an HF token instead of an OpenAI key.
client = AsyncOpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.getenv("HF_TOKEN", "YOUR_HF_TOKEN_HERE"),
)
MODEL = os.getenv("HF_MODEL", "Qwen/Qwen3-8B")

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Qwen3 can emit <think>...</think> reasoning traces in its content
    when 'thinking mode' is on -- strip them so they never reach the user."""
    return _THINK_TAG_RE.sub("", text or "").strip()

SYSTEM_PROMPT = """You are an onboarding assistant for a RISC-V learning community on Discord.

Ground rules:
- You may explain concepts, rephrase reviewed lesson content, and answer
  questions in the user's own words, adapted to their stated background --
  but never invent technical facts. Use get_current_lesson /
  get_current_quiz_question / get_current_lab to ground any explanation
  of *current* material.
- You do NOT grade quiz answers and must never tell a user their answer
  is "correct" or "incorrect" -- that only happens through the quiz
  buttons in Discord. If asked to grade, say you can't do that here and
  point them back to the quiz buttons.
- You do NOT recommend projects outside get_reviewed_projects's results,
  and never invent a project name or channel.
- You do NOT advance a user's state (track/lesson/lab/project) -- state
  changes only happen through the guided button/modal flow.
- If asked to draft a community introduction, call propose_community_intro
  with the drafted text. Do not tell the user it has been posted -- a
  separate confirmation step in Discord handles that.
- Keep answers concise and encouraging.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "Get the user's onboarding profile: goal, programming level, hardware experience, weekly hours, track, current state, selected project.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_lesson",
            "description": "Get the reviewed lesson content for the user's current track.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_quiz_question",
            "description": "Get the current reviewed quiz question's prompt and code for the user's track. Does NOT include the correct answer.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_lab",
            "description": "Get the reviewed lab exercise (starter code and goal) for the user's track.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reviewed_projects",
            "description": "Get the reviewed Project Catalog entries available for the user's track.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_community_intro",
            "description": "Propose a drafted community introduction message. Does NOT post anything -- hands the draft to a confirmation UI that the user must explicitly approve.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intro_text": {"type": "string", "description": "The drafted introduction message."}
                },
                "required": ["intro_text"],
            },
        },
    },
]


def _dispatch_tool(user_id: str, name: str, args: dict) -> dict:
    user = db.get_user(user_id) or {}
    track = user.get("track")

    if name == "get_user_profile":
        return user or {"error": "No profile yet -- user hasn't run /start"}

    if name == "get_current_lesson":
        lesson = content_bank.get_lesson(track) if track else None
        return lesson or {"error": "No track assigned yet"}

    if name == "get_current_quiz_question":
        quiz = content_bank.get_quiz(track) if track else []
        if not quiz:
            return {"error": "No quiz available yet"}
        q = dict(quiz[0])
        q.pop("correct_option", None)
        q.pop("misconception_tags", None)
        return q

    if name == "get_current_lab":
        lab = content_bank.get_lab(track) if track else None
        return lab or {"error": "No lab available yet"}

    if name == "get_reviewed_projects":
        return content_bank.get_reviewed_projects(track) if track else []

    if name == "propose_community_intro":
        return {"drafted": args.get("intro_text", "")}

    return {"error": f"Unknown tool {name}"}


async def handle_message(user_id: str, user_text: str) -> tuple[str, str | None]:
    """
    Returns (reply_text, proposed_intro_text_or_None). bot.py turns a
    proposed intro into the actual stash + confirm/decline UI -- this
    function never posts anything itself.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    proposed_intro = None

    for _ in range(4):  # cap tool-call round trips
        response = await client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return _strip_thinking(msg.content), proposed_intro

        messages.append(msg)
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments or "{}")
            result = _dispatch_tool(user_id, tool_call.function.name, args)
            if tool_call.function.name == "propose_community_intro":
                proposed_intro = args.get("intro_text", "")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

    return "Sorry, I got stuck thinking about that -- try rephrasing?", proposed_intro