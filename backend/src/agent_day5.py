import logging
import json
import os
from datetime import datetime
from typing import Annotated, List
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

# -------------------------------------------------------------------
#  ENV + LOGGING
# -------------------------------------------------------------------

load_dotenv(".env.local")
logger = logging.getLogger("sdr_agent")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # backend/
SHARED_DATA_DIR = os.path.join(BASE_DIR, "shared-data")
FAQ_FILE = os.path.join(SHARED_DATA_DIR, "day5_sdr_faq.json")

LEADS_DIR = os.path.join(BASE_DIR, "leads")
os.makedirs(LEADS_DIR, exist_ok=True)


# -------------------------------------------------------------------
#  DATA MODELS
# -------------------------------------------------------------------

@dataclass
class FAQEntry:
    id: str
    question: str
    answer: str
    tags: List[str] = field(default_factory=list)


@dataclass
class LeadState:
    name: str | None = None
    company: str | None = None
    email: str | None = None
    role: str | None = None
    use_case: str | None = None
    team_size: str | None = None
    timeline: str | None = None   # "now" / "soon" / "later"
    notes: str | None = None

    def is_complete(self) -> bool:
        return all([
            self.name,
            self.company,
            self.email,
            self.role,
            self.use_case,
        ])

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "company": self.company,
            "email": self.email,
            "role": self.role,
            "use_case": self.use_case,
            "team_size": self.team_size,
            "timeline": self.timeline,
            "notes": self.notes,
        }


@dataclass
class Userdata:
    faqs: list[FAQEntry]
    lead: LeadState = field(default_factory=LeadState)
    session_start: datetime = field(default_factory=datetime.now)


# -------------------------------------------------------------------
#  FAQ LOAD + SIMPLE SEARCH
# -------------------------------------------------------------------

def load_faqs() -> list[FAQEntry]:
    if not os.path.exists(FAQ_FILE):
        logger.warning("FAQ JSON not found at %s", FAQ_FILE)
        return []

    with open(FAQ_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    faqs: list[FAQEntry] = []
    for item in raw:
        faqs.append(
            FAQEntry(
                id=item.get("id", ""),
                question=item.get("question", ""),
                answer=item.get("answer", ""),
                tags=item.get("tags", []),
            )
        )
    logger.info("Loaded %d FAQ entries", len(faqs))
    return faqs


def search_faq(faqs: list[FAQEntry], query: str) -> FAQEntry | None:
    """Bahut simple keyword based search. Works fine for small FAQ."""

    query_lower = query.lower()
    best_score = 0
    best_entry: FAQEntry | None = None

    for entry in faqs:
        text = " ".join([entry.question, entry.answer, " ".join(entry.tags)]).lower()
        score = 0
        for term in query_lower.split():
            if term in text:
                score += 1
        if score > best_score:
            best_score = score
            best_entry = entry

    return best_entry


def save_lead_to_json(lead: LeadState, summary: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"lead_{timestamp}.json"
    path = os.path.join(LEADS_DIR, filename)

    payload = {
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "lead": lead.to_dict(),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)

    # latest_lead.json for frontend
    latest_path = os.path.join(LEADS_DIR, "latest_lead.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)

    logger.info("Lead saved to %s", path)
    return path


# -------------------------------------------------------------------
#  TOOLS – FAQ + LEAD FIELDS
# -------------------------------------------------------------------

@function_tool
async def faq_lookup(
    ctx: RunContext[Userdata],
    question: Annotated[str, Field(description="User question about product / pricing / company")],
) -> str:
    """FAQ se answer nikalne ka tool. Agar match na mile to clearly bolo."""

    entry = search_faq(ctx.userdata.faqs, question)
    if not entry:
        return (
            "Mere paas is sawal ka exact answer FAQ me nahi mila. "
            "Main sirf wahi details share karungi jo humein docs me diye gaye hain. "
            "Aap chaho to main high-level explain kar sakti hoon."
        )

    return entry.answer


@function_tool
async def set_name(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="Lead's full name")],
) -> str:
    ctx.userdata.lead.name = name.strip()
    return f"Thanks {ctx.userdata.lead.name}! Aapka naam note kar liya hai."


@function_tool
async def set_company(
    ctx: RunContext[Userdata],
    company: Annotated[str, Field(description="Lead's company / startup name")],
) -> str:
    ctx.userdata.lead.company = company.strip()
    return f"{company} – nice! Company name note ho gaya."


@function_tool
async def set_email(
    ctx: RunContext[Userdata],
    email: Annotated[str, Field(description="Work email address")],
) -> str:
    ctx.userdata.lead.email = email.strip()
    return "Great, email note ho gaya. Main isse sirf follow-up ke liye use karungi."


@function_tool
async def set_role(
    ctx: RunContext[Userdata],
    role: Annotated[str, Field(description="Role/designation of the lead")],
) -> str:
    ctx.userdata.lead.role = role.strip()
    return f"Perfect, aapki role '{role}' note kar liya."


@function_tool
async def set_use_case(
    ctx: RunContext[Userdata],
    use_case: Annotated[str, Field(description="What they want to use the product for")],
) -> str:
    ctx.userdata.lead.use_case = use_case.strip()
    return "Thanks, aapka use-case clear ho gaya, main summary me include karungi."


@function_tool
async def set_team_size(
    ctx: RunContext[Userdata],
    team_size: Annotated[str, Field(description="Team size or user count (approx)")],
) -> str:
    ctx.userdata.lead.team_size = team_size.strip()
    return "Team size note ho gaya. Isse humein fit samajhne me help milegi."


@function_tool
async def set_timeline(
    ctx: RunContext[Userdata],
    timeline: Annotated[str, Field(description="Rough timeline: now / soon / later")],
) -> str:
    ctx.userdata.lead.timeline = timeline.strip().lower()
    return f"Cool, timeline '{timeline}' ke saath main note kar leti hoon."


@function_tool
async def finalize_lead(ctx: RunContext[Userdata]) -> str:
    """Call when user says 'that's all', 'I'm done', etc."""

    lead = ctx.userdata.lead

    if not lead.is_complete():
        missing = []
        if not lead.name: missing.append("name")
        if not lead.company: missing.append("company")
        if not lead.email: missing.append("email")
        if not lead.role: missing.append("role")
        if not lead.use_case: missing.append("use case")

        return (
            "Thanks! Bas thodi si details missing hain: "
            + ", ".join(missing)
            + ". Agar aap share kar pao to main complete lead bana sakti hoon."
        )

    summary = (
        f"{lead.name} from {lead.company} works as {lead.role}. "
        f"They want to use the product for: {lead.use_case}. "
        f"Team size: {lead.team_size or 'not specified'}. "
        f"Timeline: {lead.timeline or 'not specified'}."
    )
    lead.notes = summary

    save_lead_to_json(lead, summary)

    return (
        "Perfect, main ek short summary bol deti hoon:\n"
        + summary
        + "\n\nYeh details JSON lead file me save ho chuki hain. "
        "Thank you for your time – koi bhi aur sawal ho to zaroor puchna!"
    )


# -------------------------------------------------------------------
#  SDR AGENT
# -------------------------------------------------------------------

class SDRAgent(Agent):
    def __init__(self):
        super().__init__(
           instructions="""
You are a polite, sharp Sales Development Representative (SDR) for an Indian SaaS startup called **BharatStack Cloud**.
Product: a simple, developer-friendly cloud platform for hosting APIs and web apps.

Language Rules:
- Speak ONLY in English.
- Do NOT mix Hindi or Hinglish at any point.
- Keep responses short, structured, and professional.

Conversation flow:
1. Greet the user, introduce yourself as SDR from BharatStack Cloud.
2. Ask what brought them here and what they are building.
3. When they ask product/company/pricing questions, use the `faq_lookup` tool.
4. Gradually collect lead fields:
   - name
   - company
   - role
   - email
   - use case
   - team size
   - timeline ("now", "soon", "later")
5. Focus on understanding the user's needs clearly.
6. When the user says “that's all”, “I'm done”, or “thanks”, call `finalize_lead`.

Very important:
- NEVER fabricate details, features, or pricing beyond the FAQ.
- If something is not in the FAQ, state that clearly.
- Keep a very helpful, friendly, professional tone.
""",
            tools=[
                faq_lookup,
                set_name,
                set_company,
                set_email,
                set_role,
                set_use_case,
                set_team_size,
                set_timeline,
                finalize_lead,
            ],
        )


# -------------------------------------------------------------------
#  PREWARM + ENTRYPOINT
# -------------------------------------------------------------------

def prewarm(proc: JobProcess):
    # VAD load
    proc.userdata["vad"] = silero.VAD.load()
    # FAQ preload
    proc.userdata["faqs"] = load_faqs()


async def entrypoint(ctx: JobContext):
    faqs = ctx.proc.userdata.get("faqs") or load_faqs()
    userdata = Userdata(faqs=faqs)

    
    tts = murf.TTS(
    voice="en-US-matthew",
    style="Professional",
    text_pacing=True,)


    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent):
        usage_collector.collect(ev.metrics)

    await session.start(
        agent=SDRAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
