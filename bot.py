"""
RISC-V onboarding bot -- implements the Alex end-to-end scenario as a
persisted, deterministic state machine with Discord as the UI layer.

Setup:
    1. pip install -r requirements.txt
    2. Copy .env.example to .env and fill in DISCORD_TOKEN + GUILD_ID.
    3. Download rars.jar (see emulator.py) and set RARS_JAR_PATH.
    4. python bot.py
"""

import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import db
import content_bank
import agent
from state_machine import State, HOURS_MAP, PROGRAMMING_LEVEL_MAP, HARDWARE_MAP, determine_track
from emulator import run_and_read_registers, EmulationError

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN_HERE")
GUILD_ID = os.getenv("GUILD_ID")  # set for instant guild-command sync during testing

intents = discord.Intents.default()
intents.message_content = True  # required so on_message can read free-form text for the agent
bot = commands.Bot(command_prefix="!", intents=intents)

db.init_db()

# In-memory scratch space for the *current* quiz attempt per user
# (attempt count, lab code draft). This is transient UI state, not the
# durable profile/misconception data, which always goes through db.py.
_scratch: dict[str, dict] = {}


# ---------- Step 1: /start ----------

class GoalView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Run my first RISC-V program", style=discord.ButtonStyle.primary)
    async def run_first_program(self, interaction: discord.Interaction, button: discord.ui.Button):
        db.create_or_update_user(self.user_id, state=State.PROFILE_IN_PROGRESS.value, goal="run_first_program")
        await interaction.response.send_message(
            "What best describes your programming background?",
            view=ProgrammingBackgroundView(self.user_id),
            ephemeral=True,
        )


class ProgrammingBackgroundView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        for label in PROGRAMMING_LEVEL_MAP:
            self.add_item(self._make_button(label))

    def _make_button(self, label: str):
        async def callback(interaction: discord.Interaction):
            db.create_or_update_user(self.user_id, programming_level=PROGRAMMING_LEVEL_MAP[label])
            await interaction.response.send_message(
                "Do you have any hardware or assembly experience?",
                view=HardwareBackgroundView(self.user_id),
                ephemeral=True,
            )

        btn = discord.ui.Button(label=label)
        btn.callback = callback
        return btn


class HardwareBackgroundView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        for label in HARDWARE_MAP:
            self.add_item(self._make_button(label))

    def _make_button(self, label: str):
        async def callback(interaction: discord.Interaction):
            db.create_or_update_user(self.user_id, hardware_experience=HARDWARE_MAP[label])
            await interaction.response.send_message(
                "How much time can you spend each week?",
                view=WeeklyHoursView(self.user_id),
                ephemeral=True,
            )

        btn = discord.ui.Button(label=label)
        btn.callback = callback
        return btn


class WeeklyHoursView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        for label in HOURS_MAP:
            self.add_item(self._make_button(label))

    def _make_button(self, label: str):
        async def callback(interaction: discord.Interaction):
            user = db.get_user(self.user_id)
            track = determine_track(user["programming_level"], user["hardware_experience"])
            db.create_or_update_user(
                self.user_id,
                weekly_hours=int(round(HOURS_MAP[label])),
                track=track,
                state=State.TRACK_SELECTED.value,
            )
            await interaction.response.send_message(
                f"Profile complete. You're on the **{track}** track.",
                ephemeral=True,
            )
            await send_lesson(interaction, self.user_id)

        btn = discord.ui.Button(label=label)
        btn.callback = callback
        return btn


@bot.tree.command(name="start", description="Begin RISC-V onboarding")
async def start(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    existing = db.get_user(user_id)
    if existing and existing["state"] != State.PROFILE_IN_PROGRESS.value:
        await resume(interaction, existing)
        return
    db.create_or_update_user(user_id, state=State.PROFILE_IN_PROGRESS.value)
    await interaction.response.send_message(
        "What would make today feel successful?",
        view=GoalView(user_id),
        ephemeral=True,
    )


async def resume(interaction: discord.Interaction, user: dict):
    """Restart-resilience: routes the user back into whatever state they left."""
    state = user["state"]
    user_id = user["user_id"]
    if state == State.TRACK_SELECTED.value:
        await interaction.response.send_message("Welcome back -- continuing your lesson.", ephemeral=True)
        await send_lesson(interaction, user_id)
    elif state == State.LEARNING.value:
        await interaction.response.send_message("Welcome back -- here's your quiz question again.", ephemeral=True)
        await send_quiz(interaction, user_id)
    elif state == State.LAB_UNLOCKED.value:
        await interaction.response.send_message("Welcome back -- here's your lab.", ephemeral=True)
        await send_lab(interaction, user_id)
    elif state == State.LAB_COMPLETE.value:
        await interaction.response.send_message("Welcome back -- pick a project to continue.", ephemeral=True)
        await send_project_recommendations(interaction, user_id)
    elif state == State.PROJECT_SELECTED.value or state == State.COMMUNITY_HANDOFF_PENDING.value:
        await interaction.response.send_message("Welcome back -- confirm your community intro.", ephemeral=True)
        await send_completion(interaction, user_id)
    else:
        await interaction.response.send_message(
            "What would make today feel successful?", view=GoalView(user_id), ephemeral=True
        )


# ---------- Step 3: Lesson ----------

async def send_lesson(interaction: discord.Interaction, user_id: str):
    user = db.get_user(user_id)
    lesson = content_bank.get_lesson(user["track"])
    db.set_state(user_id, State.LEARNING.value)
    await interaction.followup.send(f"**{lesson['title']}**\n{lesson['body']}", ephemeral=True)
    await send_quiz(interaction, user_id)


# ---------- Step 4: Quiz / misconception handling ----------

class QuizView(discord.ui.View):
    def __init__(self, user_id: str, question: dict):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.question = question
        for opt in question["options"]:
            self.add_item(self._make_button(opt))

    def _make_button(self, option: str):
        async def callback(interaction: discord.Interaction):
            q = self.question
            key = f"{self.user_id}:{q['id']}"
            attempt = _scratch.setdefault(key, {"attempts": 0})
            attempt["attempts"] += 1

            if option == q["correct_option"]:
                if attempt["attempts"] > 1:
                    # It was previously wrong and is now repaired -- resolve the
                    # most recent misconception tag for this user privately.
                    for tag in q["misconception_tags"].values():
                        db.resolve_misconception(self.user_id, tag)
                await interaction.response.send_message(
                    f"Correct. {q['explanation']}", ephemeral=True
                )
                db.set_state(self.user_id, State.LAB_UNLOCKED.value)
                await send_lab(interaction, self.user_id)
            else:
                tag = q["misconception_tags"].get(option, "unspecified-misconception")
                # Private record only -- never referenced in any public draft.
                db.record_misconception(self.user_id, tag)
                await interaction.response.send_message(
                    f"Not quite. {q['explanation']} Try again.",
                    view=QuizView(self.user_id, q),
                    ephemeral=True,
                )

        btn = discord.ui.Button(label=option)
        btn.callback = callback
        return btn


async def send_quiz(interaction: discord.Interaction, user_id: str):
    user = db.get_user(user_id)
    quiz = content_bank.get_quiz(user["track"])
    if not quiz:
        db.set_state(user_id, State.LAB_UNLOCKED.value)
        await send_lab(interaction, user_id)
        return
    question = quiz[0]
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(
        f"{question['prompt']}\n```asm\n{question['code']}\n```",
        view=QuizView(user_id, question),
        ephemeral=True,
    )


# ---------- Step 5: Lab, verified by the emulator ----------

class LabSubmitModal(discord.ui.Modal, title="Submit your lab code"):
    code_input = discord.ui.TextInput(
        label="RISC-V assembly", style=discord.TextStyle.paragraph, required=True
    )

    def __init__(self, user_id: str, lab: dict):
        super().__init__()
        self.user_id = user_id
        self.lab = lab
        self.code_input.default = lab["starter_code"]

    async def on_submit(self, interaction: discord.Interaction):
        lab = self.lab
        try:
            registers = run_and_read_registers(str(self.code_input), ["t0", "t1", "t2"])
        except EmulationError as e:
            await interaction.response.send_message(f"Couldn't run that: {e}", ephemeral=True)
            return

        trace = " -> ".join(f"{r}: {v}" for r, v in registers.items())
        target = self.lab["target_register"]
        if registers.get(target) == self.lab["target_value"]:
            db.set_state(self.user_id, State.LAB_COMPLETE.value)
            await interaction.response.send_message(
                f"Trace: {trace}\nGoal met -- {target} = {self.lab['target_value']}. Lab complete!",
                ephemeral=True,
            )
            await send_project_recommendations(interaction, self.user_id)
        else:
            await interaction.response.send_message(
                f"Trace: {trace}\nNot quite -- {target} should be {self.lab['target_value']}. Try again.",
                ephemeral=True,
            )


async def send_lab(interaction: discord.Interaction, user_id: str):
    user = db.get_user(user_id)
    lab = content_bank.get_lab(user["track"])

    class LabView(discord.ui.View):
        @discord.ui.button(label="Submit code", style=discord.ButtonStyle.primary)
        async def submit(self, i: discord.Interaction, button: discord.ui.Button):
            await i.response.send_modal(LabSubmitModal(user_id, lab))

    text = f"**Goal:** {lab['goal_text']}\n```asm\n{lab['starter_code']}\n```"
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(text, view=LabView(), ephemeral=True)


# ---------- Step 6: Project recommendation ----------

class ProjectSelectView(discord.ui.View):
    def __init__(self, user_id: str, projects: list[dict]):
        super().__init__(timeout=300)
        self.user_id = user_id
        for project in projects:
            self.add_item(self._make_button(project))

    def _make_button(self, project: dict):
        async def callback(interaction: discord.Interaction):
            db.create_or_update_user(
                self.user_id, selected_project=project["id"], state=State.PROJECT_SELECTED.value
            )
            await interaction.response.send_message(f"Selected: **{project['title']}**", ephemeral=True)
            await send_completion(interaction, self.user_id)

        btn = discord.ui.Button(label=project["title"])
        btn.callback = callback
        return btn


async def send_project_recommendations(interaction: discord.Interaction, user_id: str):
    user = db.get_user(user_id)
    projects = content_bank.get_reviewed_projects(user["track"])
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(
        "Recommended projects for you:",
        view=ProjectSelectView(user_id, projects),
        ephemeral=True,
    )


# ---------- Step 7: Completion + confirmation-gated community post ----------

class CommunityHandoffView(discord.ui.View):
    def __init__(self, user_id: str, channel_name: str, draft_text: str):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.channel_name = channel_name
        self.draft_text = draft_text

    @discord.ui.button(label="Post my introduction", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Look up the channel by name in the guild and post ONLY on this explicit click.
        channel = discord.utils.get(interaction.guild.text_channels, name=self.channel_name.lstrip("#"))
        if channel:
            await channel.send(self.draft_text)
            await interaction.response.send_message(f"Posted to {channel.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Couldn't find #{self.channel_name} -- ask a mod to create it, then try again.",
                ephemeral=True,
            )
        db.clear_confirmation(self.user_id)

    @discord.ui.button(label="Not yet", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("No problem -- nothing was posted.", ephemeral=True)


async def send_completion(interaction: discord.Interaction, user_id: str):
    user = db.get_user(user_id)
    projects = {p["id"]: p for p in content_bank.get_reviewed_projects(user["track"])}
    project = projects.get(user["selected_project"])
    if not project:
        return

    draft = (
        f"Hi! I'm new here and just picked up **{project['title']}** as my first project. "
        f"Goal: {project['description']} Looking forward to learning alongside everyone!"
    )
    db.stash_confirmation(user_id, project["recommended_channel"], draft)
    db.set_state(user_id, State.COMMUNITY_HANDOFF_PENDING.value)

    summary = (
        f"**Project:** {project['title']}\n"
        f"**Estimated time:** {project['estimated_time']}\n"
        f"**First task:** {project['first_task']}\n"
        f"**Definition of done:** {project['definition_of_done']}\n"
        f"**Recommended channel:** {project['recommended_channel']}\n\n"
        f"**Draft introduction:**\n> {draft}\n\n"
        "Nothing is posted until you confirm below."
    )
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(
        summary,
        view=CommunityHandoffView(user_id, project["recommended_channel"], draft),
        ephemeral=True,
    )


@bot.event
async def on_message(message: discord.Message):
    """
    Routes free-form messages (DMs or @mentions) to the agent for Q&A,
    adaptive explanations, and intro drafting. This is separate from the
    guided /start flow above -- the agent never advances state or grades
    anything; it can only answer, explain, and propose a draft intro.
    """
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = bot.user in message.mentions
    if not (is_dm or is_mention):
        return

    content = message.content
    if is_mention:
        content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    if not content:
        return

    user_id = str(message.author.id)
    async with message.channel.typing():
        try:
            reply_text, proposed_intro = await agent.handle_message(user_id, content)
        except Exception as e:
            reply_text, proposed_intro = f"Sorry, I hit an error: `{e}`", None

    if reply_text:
        for chunk_start in range(0, len(reply_text), 2000):
            await message.channel.send(reply_text[chunk_start:chunk_start + 2000])

    if proposed_intro:
        user = db.get_user(user_id)
        project = None
        if user and user.get("track") and user.get("selected_project"):
            projects = {p["id"]: p for p in content_bank.get_reviewed_projects(user["track"])}
            project = projects.get(user["selected_project"])
        channel_name = project["recommended_channel"] if project else "general"

        db.stash_confirmation(user_id, channel_name, proposed_intro)
        await message.channel.send(
            f"Here's a draft:\n> {proposed_intro}\n\nWant me to post this to {channel_name}?",
            view=CommunityHandoffView(user_id, channel_name, proposed_intro),
        )


@bot.event
async def on_ready():
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    print(f"Logged in as {bot.user}")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)