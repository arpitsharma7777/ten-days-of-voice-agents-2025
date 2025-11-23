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
    RoomInputOptions,
    WorkerOptions,
    RunContext,
    function_tool,
    cli,
    metrics,
    MetricsCollectedEvent,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# Load environment variables
load_dotenv(".env.local")
logger = logging.getLogger("agent")


# ======================================================
# ORDER STATE
# ======================================================
@dataclass
class OrderState:
    drinkType: str | None = None
    size: str | None = None
    milk: str | None = None
    extras: list[str] = field(default_factory=list)
    name: str | None = None

    def is_complete(self):
        return all([
            self.drinkType,
            self.size,
            self.milk,
            self.extras is not None,
            self.name
        ])

    def to_dict(self):
        return {
            "drinkType": self.drinkType,
            "size": self.size,
            "milk": self.milk,
            "extras": self.extras,
            "name": self.name
        }

    def get_summary(self):
        if not self.is_complete():
            return "Order is still in progress."
        extras_text = ", ".join(self.extras) if self.extras else "no extras"
        return f"{self.size.title()} {self.drinkType.title()} with {self.milk.title()} milk and {extras_text} for {self.name}"


@dataclass
class Userdata:
    order: OrderState
    session_start: datetime = field(default_factory=datetime.now)


# ======================================================
# FUNCTION TOOLS
# ======================================================

@function_tool
async def set_drink_type(
    ctx: RunContext[Userdata],
    drink: Annotated[
        Literal["latte", "cappuccino", "americano", "espresso", "mocha", "coffee", "cold brew", "matcha"],
        Field(description="Type of drink the user wants.")
    ],
):
    ctx.userdata.order.drinkType = drink
    return f"Great, one {drink} coming right up!"


@function_tool
async def set_size(
    ctx: RunContext[Userdata],
    size: Annotated[
        Literal["small", "medium", "large", "extra large"],
        Field(description="Size of the drink.")
    ],
):
    ctx.userdata.order.size = size
    return f"{size.title()} size noted."


@function_tool
async def set_milk(
    ctx: RunContext[Userdata],
    milk: Annotated[
        Literal["whole", "skim", "almond", "oat", "soy", "coconut", "none"],
        Field(description="Milk preference.")
    ],
):
    ctx.userdata.order.milk = milk
    if milk == "none":
        return "Going with no milk. Got it!"
    return f"{milk.title()} milk added."


@function_tool
async def set_extras(
    ctx: RunContext[Userdata],
    extras: Annotated[
        list[Literal["sugar", "whipped cream", "caramel", "extra shot", "vanilla", "cinnamon", "honey"]] | None,
        Field(description="Extra add-ons.")
    ] = None,
):
    ctx.userdata.order.extras = extras if extras else []
    if extras:
        return f"Added: {', '.join(extras)}."
    return "No extras added."


@function_tool
async def set_name(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="Customer name for the order.")],
):
    ctx.userdata.order.name = name.strip().title()
    return f"Thanks, {ctx.userdata.order.name}! Almost done."


@function_tool
async def cancel_order(ctx: RunContext[Userdata]):
    """Cancel the current order and reset the order state."""
    ctx.userdata.order = OrderState()  # Reset order
    return "Your order has been canceled. If you'd like to start a new one, just tell me what you'd like to drink."


@function_tool
async def complete_order(ctx: RunContext[Userdata]):
    order = ctx.userdata.order
    if not order.is_complete():
        missing = []
        if not order.drinkType: missing.append("drink type")
        if not order.size: missing.append("size")
        if not order.milk: missing.append("milk")
        if order.extras is None: missing.append("extras")
        if not order.name: missing.append("name")
        return f"I still need: {', '.join(missing)}."

    # 1) Save order to JSON file (Day 2 primary requirement)
    save_order_to_json(order)

    # 2) Send order state to frontend via LiveKit data packets
    try:
        room = ctx.session.room  # RunContext se session, phir room
        payload = {
            "type": "order_state",
            "order": order.to_dict(),
        }
        await room.local_participant.publish_data(
            json.dumps(payload).encode("utf-8"),
            topic="order_state",
        )
    except Exception as e:
        logger.exception(f"Failed to publish order_state: {e}")

    # 3) Normal voice reply
    return f"Your order is complete: {order.get_summary()}. We’ll start preparing it now!"



# ======================================================
# ORDER SAVE HANDLER
# ======================================================
def get_orders_folder():
    base_dir = os.path.dirname(__file__)
    backend_dir = os.path.abspath(os.path.join(base_dir, ".."))
    folder = os.path.join(backend_dir, "orders")
    os.makedirs(folder, exist_ok=True)
    return folder


def save_order_to_json(order: OrderState):
    folder = get_orders_folder()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, f"order_{timestamp}.json")

    data = order.to_dict()
    data["timestamp"] = datetime.now().isoformat()
    data["session_id"] = timestamp

    with open(path, "w") as f:
        json.dump(data, f, indent=4)

    print(f"[ORDER SAVED] {path}")


# ======================================================
# BARISTA AGENT
# ======================================================
class BaristaAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are a friendly coffee shop barista.

Guide the customer through the order step-by-step:
1. Ask for drink type.
2. Ask for size.
3. Ask for milk.
4. Ask for extras.
5. Ask for their name.

If the customer wants to cancel the order, call the cancel_order tool.

When all details are collected, call complete_order.
""",
            tools=[
                set_drink_type,
                set_size,
                set_milk,
                set_extras,
                set_name,
                complete_order,
                cancel_order,
            ],
        )


# ======================================================
# SESSION MANAGEMENT
# ======================================================
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    userdata = Userdata(order=OrderState())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Conversation",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _metrics(ev: MetricsCollectedEvent):
        usage_collector.collect(ev.metrics)

    await session.start(
        agent=BaristaAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()


# ======================================================
# BOOTSTRAP
# ======================================================
if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
