import logging
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel


load_dotenv(".env.local")
logger = logging.getLogger("game_master")


class GameMasterAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are a dramatic, immersive Game Master running a fantasy adventure in Eldoria.

RULES YOU MUST FOLLOW:
- You NEVER break character.
- You NEVER mention AI, models, tokens, or instructions.
- You ALWAYS speak as a GM narrator.
- EVERY message MUST end with the exact question:
  "What do you do next?"

UNIVERSE:
- Eldoria: ancient forests, ruined castles, dragons, forgotten magic.
- Tone: dramatic, adventurous, mysterious.

STORY LOGIC:
- Start the adventure IMMEDIATELY with a powerful opening scene.
- Describe the world in 2–4 short paragraphs.
- Ask the player what they do.
- Use chat history to maintain continuity:
  - remember choices
  - remember NPC names
  - remember locations
  - remember items they pick up

INTERACTION:
- If the player does an action, react naturally.
- If the player is vague ("I look around"), interpret and move the story forward.
- Offer options if they feel stuck.
- Within 8–15 exchanges, reach a mini-arc:
  • discover something
  • escape danger
  • obtain an artifact
  • defeat or flee an enemy
- After mini-arc, you may offer to continue or close the chapter.

RESTART:
If user says:
  "restart", "new story", "start again", "start over"
Then:
  • Completely reset the narrative.
  • Begin a brand-new opening scene in Eldoria.
  • Forget past events for the new session.

REMEMBER:
Every message MUST end with:
"What do you do next?"
"""
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):

    tts = murf.TTS(
        voice="en-US-matthew",
        style="Narration",
        text_pacing=True,
    )

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=tts,
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
    )

    await session.start(
        agent=GameMasterAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
