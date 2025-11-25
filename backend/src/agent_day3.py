import logging
import json
import os
from datetime import datetime
from typing import Annotated
from dataclasses import dataclass, field

from dotenv import load_dotenv
from pydantic import Field

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    RoomInputOptions,
    WorkerOptions,
    function_tool,
    cli,
    metrics,
    MetricsCollectedEvent,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")
logger = logging.getLogger("wellness")

# ======================================================
#   Wellness State
# ======================================================

@dataclass
class WellnessState:
    mood: str | None = None
    energy: str | None = None
    stress: str | None = None
    goals: list[str] = field(default_factory=list)
    summary: str | None = None

@dataclass
class Userdata:
    wellness: WellnessState
    session_start: datetime = field(default_factory=datetime.now)

WELLNESS_FOLDER = os.path.join(os.path.dirname(__file__), "..", "wellness")
os.makedirs(WELLNESS_FOLDER, exist_ok=True)

LOG_FILE = os.path.join(WELLNESS_FOLDER, "wellness_log.json")

# ======================================================
#   JSON Read & Write
# ======================================================

def load_previous_entries():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_entry(entry: dict):
    data = load_previous_entries()
    data.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ======================================================
#   LLM Tools
# ======================================================

@function_tool
async def set_mood(ctx: RunContext[Userdata], mood: Annotated[str, Field(description="User's emotional mood")] ):
    ctx.userdata.wellness.mood = mood
    return f"Thanks for sharing. I understand you're feeling {mood}."

@function_tool
async def set_energy(ctx: RunContext[Userdata], energy: Annotated[str, Field(description="Energy level today")] ):
    ctx.userdata.wellness.energy = energy
    return f"Got it. Your energy level is {energy}."

@function_tool
async def set_stress(ctx: RunContext[Userdata], stress: Annotated[str, Field(description="Stress or worries today")] ):
    ctx.userdata.wellness.stress = stress
    return "Thanks for being honest about what's stressing you."

@function_tool
async def set_goals(ctx: RunContext[Userdata], 
    goals: Annotated[list[str], Field(description="1-3 simple goals for today")]):
    ctx.userdata.wellness.goals = goals
    return f"Noted your goals: {', '.join(goals)}."

@function_tool
async def complete_checkin(ctx: RunContext[Userdata]):
    w = ctx.userdata.wellness

    if not (w.mood and w.energy and w.stress and w.goals):
        return "We still haven't covered everything. Please continue."

    summary = f"Today you are feeling {w.mood}, energy is {w.energy}, stress from {w.stress}, and your goals are {', '.join(w.goals)}."
    w.summary = summary

    entry = {
        "timestamp": datetime.now().isoformat(),
        "mood": w.mood,
        "energy": w.energy,
        "stress": w.stress,
        "goals": w.goals,
        "summary": w.summary
    }

    save_entry(entry)
    return f"Your check-in is saved. Summary: {summary}"

@function_tool
async def read_past(ctx: RunContext[Userdata]):
    data = load_previous_entries()
    if not data:
        return "This seems like our first check-in together."

    last = data[-1]
    return f"Last time you said your mood was {last['mood']} and your energy was {last['energy']}. How does today compare?"

# ======================================================
#   Agent Instructions
# ======================================================

class WellnessAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are a supportive Health & Wellness Voice Companion.

Do not provide medical advice.
Do not diagnose conditions.

Each session, follow this structure:
1. Ask how the user feels today (mood).
2. Ask about energy levels.
3. Ask if anything is stressing them.
4. Ask for 1–3 simple goals for today.
5. Offer small, grounded suggestions (like taking a break or breaking tasks into smaller pieces).
6. Recap the full day and confirm.
7. Save the check-in using complete_checkin.

If user asks about past progress, call read_past.
""",
            tools=[set_mood, set_energy, set_stress, set_goals, complete_checkin, read_past],
        )

# ======================================================
#   Session
# ======================================================

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    userdata = Userdata(wellness=WellnessState())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-matthew", style="Conversation", text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata
    )

    await session.start(
        agent=WellnessAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
