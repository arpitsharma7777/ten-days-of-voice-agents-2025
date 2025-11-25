import logging
import json
import os
from datetime import datetime
from typing import Annotated, Literal
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

# ---------- env & logger ----------
load_dotenv(".env.local")
logger = logging.getLogger("day4_tutor")

# ======================================================
#   Content loading (JSON course file)
# ======================================================

BASE_DIR = os.path.dirname(__file__)
CONTENT_PATH = os.path.join(BASE_DIR, "..", "shared-data", "day4_tutor_content.json")

def load_tutor_content() -> list[dict]:
    try:
        with open(CONTENT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Day4 content file not found at %s", CONTENT_PATH)
        return []

TUTOR_CONTENT = load_tutor_content()
CONCEPT_BY_ID = {c["id"]: c for c in TUTOR_CONTENT}

# ======================================================
#   Progress persistence (for frontend card)
# ======================================================

TUTOR_FOLDER = os.path.join(BASE_DIR, "..", "tutor")
os.makedirs(TUTOR_FOLDER, exist_ok=True)
PROGRESS_FILE = os.path.join(TUTOR_FOLDER, "tutor_progress.json")

def load_progress() -> dict:
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_progress(data: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def bump_progress(concept_id: str, mode: str):
    data = load_progress()
    c = data.setdefault(
        concept_id,
        {"learn": 0, "quiz": 0, "teach_back": 0, "last_updated": None},
    )
    if mode in ("learn", "quiz", "teach_back"):
        c[mode] += 1
        c["last_updated"] = datetime.now().isoformat()
        save_progress(data)

# ======================================================
#   Tutor state
# ======================================================

@dataclass
class TutorState:
    mode: Literal["learn", "quiz", "teach_back"] = "learn"
    current_concept_id: str | None = None

@dataclass
class Userdata:
    tutor: TutorState
    session_start: datetime = field(default_factory=datetime.now)

# ======================================================
#   Tools (LLM helpers)
# ======================================================

def _get_default_concept_id() -> str | None:
    return TUTOR_CONTENT[0]["id"] if TUTOR_CONTENT else None

@function_tool
async def set_mode(
    ctx: RunContext[Userdata],
    mode: Annotated[
        Literal["learn", "quiz", "teach_back"],
        Field(description="Learning mode: learn, quiz, or teach_back"),
    ],
) -> str:
    """Set the active learning mode for the tutor."""
    ctx.userdata.tutor.mode = mode
    # Optional: yahan pe alag voice set kar sakte ho agar murf.TTS mutable ho
    if mode == "learn":
        return "Switched to LEARN mode. I’ll explain concepts step by step."
    if mode == "quiz":
        return "Switched to QUIZ mode. I’ll ask you questions to test understanding."
    return "Switched to TEACH-BACK mode. You’ll explain concepts to me and I’ll give feedback."

@function_tool
async def set_concept(
    ctx: RunContext[Userdata],
    concept_id: Annotated[
        str,
        Field(
            description=(
                "ID of concept to focus on. "
                "Expected values: " + ", ".join(CONCEPT_BY_ID.keys())
            )
        ),
    ],
) -> str:
    """Choose which concept the user wants to study."""
    if concept_id not in CONCEPT_BY_ID:
        return f"I don’t know the concept '{concept_id}'. Available ones are: {', '.join(CONCEPT_BY_ID.keys())}."
    ctx.userdata.tutor.current_concept_id = concept_id
    concept = CONCEPT_BY_ID[concept_id]
    return f"Great, we’ll work on {concept['title']}."

@function_tool
async def learn_concept(ctx: RunContext[Userdata]) -> str:
    """
    Explain the current concept in a clear, concise way,
    using the summary from the content file.
    """
    concept_id = ctx.userdata.tutor.current_concept_id or _get_default_concept_id()
    if not concept_id or concept_id not in CONCEPT_BY_ID:
        return "I don’t have any concepts loaded. Please pick a topic like 'variables' or 'loops'."

    ctx.userdata.tutor.current_concept_id = concept_id
    concept = CONCEPT_BY_ID[concept_id]
    bump_progress(concept_id, "learn")

    return (
        f"Let’s learn **{concept['title']}**.\n\n"
        f"{concept['summary']}\n\n"
        "When you’re ready, you can say something like: "
        "'Quiz me on this' or 'Let me teach it back'."
    )

@function_tool
async def quiz_concept(ctx: RunContext[Userdata]) -> str:
    """
    Ask a core question about the current concept, using sample_question.
    The LLM should WAIT for the user's spoken answer after this.
    """
    concept_id = ctx.userdata.tutor.current_concept_id or _get_default_concept_id()
    if not concept_id or concept_id not in CONCEPT_BY_ID:
        return "First choose a concept to quiz on, for example 'variables' or 'loops'."

    ctx.userdata.tutor.current_concept_id = concept_id
    concept = CONCEPT_BY_ID[concept_id]
    bump_progress(concept_id, "quiz")

    return (
        f"Quiz time for **{concept['title']}**.\n"
        f"Question: {concept['sample_question']}\n\n"
        "Answer in your own words, and then I’ll react to it."
    )

@function_tool
async def teach_back_prompt(ctx: RunContext[Userdata]) -> str:
    """
    Ask the user to explain the concept back in their own words.
    The LLM should listen and then give encouraging, qualitative feedback.
    """
    concept_id = ctx.userdata.tutor.current_concept_id or _get_default_concept_id()
    if not concept_id or concept_id not in CONCEPT_BY_ID:
        return "Pick a concept first, then we’ll do a teach-back round."

    ctx.userdata.tutor.current_concept_id = concept_id
    concept = CONCEPT_BY_ID[concept_id]
    bump_progress(concept_id, "teach_back")

    return (
        f"Teach-back round on **{concept['title']}**.\n"
        "Without reading anything, explain this concept to me in your own words. "
        "Try to include what it is, why it’s useful, and at least one simple example."
    )

@function_tool
async def list_concepts(ctx: RunContext[Userdata]) -> str:
    """List the available concepts and IDs for the user."""
    if not TUTOR_CONTENT:
        return "No tutor content is configured yet."
    lines = []
    for c in TUTOR_CONTENT:
        lines.append(f"- {c['title']} (id: {c['id']})")
    return "Here are the concepts you can study:\n" + "\n".join(lines)

# ======================================================
#   Agent instructions
# ======================================================

def _build_instructions() -> str:
    concept_titles = ", ".join(c["title"] for c in TUTOR_CONTENT) or "no content"
    return f"""
You are an *Active Recall Coding Tutor*.

Goal:
Help the user deeply understand programming concepts using three modes:
- **learn**  – you explain the concept clearly.
- **quiz**   – you ask questions and wait for answers.
- **teach_back** – the user explains back, you give short qualitative feedback.

Available concepts (from a JSON content file): {concept_titles}.
Use tools like list_concepts and set_concept to pick topics.

Conversation flow:
1. Greet the user and briefly explain the three modes.
2. Ask which mode they want first (learn / quiz / teach_back) and which concept.
3. Use set_mode + set_concept, then call the matching tool:
   - learn_concept in learn mode
   - quiz_concept in quiz mode
   - teach_back_prompt in teach_back mode
4. Let the user switch modes any time if they ask.
5. After each answer in quiz / teach_back, give constructive but brief feedback.
6. Keep explanations short and concrete. No long lectures.

VERY IMPORTANT:
- Do NOT hallucinate new concepts that are not in the content file.
- Never claim to be a medical or mental-health professional.
- If the user asks for something outside this tutor scope, gently steer back.
"""

class TutorAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=_build_instructions(),
            tools=[
                set_mode,
                set_concept,
                learn_concept,
                quiz_concept,
                teach_back_prompt,
                list_concepts,
            ],
        )

# ======================================================
#   Session setup
# ======================================================

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    userdata = Userdata(tutor=TutorState())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",   # base voice; agar chaaho to mode ke hisaab se mutate kar sakte ho
            style="Conversation",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    usage = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage.collect(ev.metrics)

    await session.start(
        agent=TutorAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
