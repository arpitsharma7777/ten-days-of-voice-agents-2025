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

# ---------------------------------------------------------
# ENV + LOGGING
# ---------------------------------------------------------

load_dotenv(".env.local")
logger = logging.getLogger("fraud_agent")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # backend/
FRAUD_DIR = os.path.join(BASE_DIR, "fraud")
os.makedirs(FRAUD_DIR, exist_ok=True)

CASE_FILE = os.path.join(FRAUD_DIR, "fraud_case.json")


# ---------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------

@dataclass
class FraudCase:
    userName: str
    securityIdentifier: str
    securityQuestion: str
    securityAnswer: str

    cardEnding: str
    transactionAmount: str
    transactionName: str
    transactionTime: str
    transactionLocation: str
    transactionCategory: str
    transactionSource: str

    status: str = "pending_review"
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "FraudCase":
        return cls(
            userName=data.get("userName", ""),
            securityIdentifier=data.get("securityIdentifier", ""),
            securityQuestion=data.get("securityQuestion", ""),
            securityAnswer=data.get("securityAnswer", ""),
            cardEnding=data.get("cardEnding", ""),
            transactionAmount=data.get("transactionAmount", ""),
            transactionName=data.get("transactionName", ""),
            transactionTime=data.get("transactionTime", ""),
            transactionLocation=data.get("transactionLocation", ""),
            transactionCategory=data.get("transactionCategory", ""),
            transactionSource=data.get("transactionSource", ""),
            status=data.get("status", "pending_review"),
            notes=data.get("notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "userName": self.userName,
            "securityIdentifier": self.securityIdentifier,
            "securityQuestion": self.securityQuestion,
            "securityAnswer": self.securityAnswer,
            "cardEnding": self.cardEnding,
            "transactionAmount": self.transactionAmount,
            "transactionName": self.transactionName,
            "transactionTime": self.transactionTime,
            "transactionLocation": self.transactionLocation,
            "transactionCategory": self.transactionCategory,
            "transactionSource": self.transactionSource,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class Userdata:
    fraud_cases: List[FraudCase] = field(default_factory=list)
    fraud_case: FraudCase | None = None
    verified_username: bool = False
    verified_security: bool = False
    verification_attempts: int = 0
    session_start: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------
# JSON LOAD + SAVE (MULTI CASE SUPPORT)
# ---------------------------------------------------------

def load_all_fraud_cases() -> list[FraudCase]:
    if not os.path.exists(CASE_FILE):
        raise FileNotFoundError(f"Fraud case JSON not found at {CASE_FILE}")

    with open(CASE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        raw = [raw]

    return [FraudCase.from_dict(x) for x in raw]


def save_all_fraud_cases(cases: list[FraudCase]) -> None:
    with open(CASE_FILE, "w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in cases], f, indent=4, ensure_ascii=False)


def find_case_by_username(cases: list[FraudCase], username: str):
    username = username.strip().lower()
    for case in cases:
        if case.userName.strip().lower() == username:
            return case
    return None


# ---------------------------------------------------------
# TOOLS
# ---------------------------------------------------------

@function_tool
async def verify_username(
    ctx: RunContext[Userdata],
    username: Annotated[str, Field(description="Name the caller claims to be.")],
):
    claimed = username.strip().lower()

    match = find_case_by_username(ctx.userdata.fraud_cases, claimed)
    if not match:
        ctx.userdata.verification_attempts += 1
        return (
            "I could not locate any fraud alert case under that name. "
            "Please try again with the correct account name."
        )

    ctx.userdata.fraud_case = match
    ctx.userdata.verified_username = True

    return (
        f"Thank you {match.userName}. I have located your fraud alert case. "
        "For security, please answer a quick verification question."
    )


@function_tool
async def verify_security_answer(
    ctx: RunContext[Userdata],
    answer: Annotated[str, Field(description="Answer to the security question.")],
):
    c = ctx.userdata.fraud_case

    if not c:
        return "We have not found your case yet. Please provide your name first."

    if answer.strip().lower() == c.securityAnswer.strip().lower():
        ctx.userdata.verified_security = True
        return "Thank you. Your identity is verified."
    else:
        ctx.userdata.verification_attempts += 1
        return "That answer does not match our records."


@function_tool
async def get_transaction_summary(ctx: RunContext[Userdata]):
    c = ctx.userdata.fraud_case
    if not c:
        return "We have not accessed your case yet."

    return (
        f"There is a transaction of {c.transactionAmount} at {c.transactionName} "
        f"in {c.transactionLocation} on {c.transactionTime}. "
        f"The card used ends in {c.cardEnding}. "
        f"It is categorized as {c.transactionCategory}, sourced from {c.transactionSource}."
    )


def update_case(ctx: RunContext[Userdata], status: str, notes: str):
    c = ctx.userdata.fraud_case
    all_cases = ctx.userdata.fraud_cases

    c.status = status
    c.notes = notes

    # update entry
    for i, case in enumerate(all_cases):
        if case.userName.lower() == c.userName.lower():
            all_cases[i] = c
            break

    save_all_fraud_cases(all_cases)


@function_tool
async def mark_transaction_safe(ctx: RunContext[Userdata]):
    update_case(ctx, "confirmed_safe", "Customer confirmed transaction as legitimate.")
    return "I have marked this transaction as safe."


@function_tool
async def mark_transaction_fraud(ctx: RunContext[Userdata]):
    update_case(ctx, "confirmed_fraud", "Customer denied transaction. (Demo only.)")
    return "I have marked this transaction as fraudulent."


@function_tool
async def mark_verification_failed(ctx: RunContext[Userdata]):
    update_case(ctx, "verification_failed", "Identity verification failed.")
    return (
        "Since we could not verify your identity, I cannot continue. "
        "Please contact SecureTrust Bank through official channels."
    )


# ---------------------------------------------------------
# AGENT
# ---------------------------------------------------------

class FraudAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are a calm, professional fraud detection representative from SecureTrust Bank.

IMPORTANT RULE:
You MUST ALWAYS read the security question stored in the fraud_case object:
- Do NOT invent your own question.
- Do NOT change the wording.
- Only ask exactly: ctx.userdata.fraud_case.securityQuestion

Flow:
1. Ask for name → call verify_username.
2. After username is verified, say EXACTLY:
   "For verification, your security question is: <securityQuestion>. Please answer it."
3. Wait for the user's answer → call verify_security_answer.
4. If verified, read the transaction (get_transaction_summary).
5. Ask if they made the transaction.
6. Depending on yes/no → call mark_transaction_safe or mark_transaction_fraud.
7. If verification fails → call mark_verification_failed.
8. You must NOT invent your own security question. Always wait for the system-provided security question.

NEVER ask:
- Date of birth
- Card numbers
- PIN
- CVV
- OTP
- Email/password
- Anything not in JSON.

Keep responses short, clear, and professional.
"""
,
            tools=[
                verify_username,
                verify_security_answer,
                get_transaction_summary,
                mark_transaction_safe,
                mark_transaction_fraud,
                mark_verification_failed,
            ],
        )


# ---------------------------------------------------------
# PREWARM + ENTRYPOINT
# ---------------------------------------------------------

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["fraud_cases"] = load_all_fraud_cases()


async def entrypoint(ctx: JobContext):
    all_cases = ctx.proc.userdata["fraud_cases"]
    userdata = Userdata(fraud_cases=all_cases)

    tts = murf.TTS(
        voice="en-US-matthew",
        style="Professional",
        text_pacing=True,
    )

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    # -----------------------
    # FORCE SECURITY QUESTION
    # -----------------------
    def enforce_security_question(ev):
        ud = session.userdata

        if ud.fraud_case and ud.verified_username and not ud.verified_security:
            real_q = ud.fraud_case.securityQuestion

            async def injector():
                session.agent.override_next_user_prompt(
                    f"For verification, your security question is: {real_q}. Please answer it."
                )

            asyncio.create_task(injector())

    session.on("agent_message", enforce_security_question)

    # -----------------------
    # START SESSION
    # -----------------------
    await session.start(
        agent=FraudAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()



if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
