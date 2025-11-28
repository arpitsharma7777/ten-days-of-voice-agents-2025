import logging
import json
import os
from datetime import datetime
from typing import Annotated, List, Dict
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
logger = logging.getLogger("food_agent")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # backend/
SHARED_DATA_DIR = os.path.join(BASE_DIR, "shared-data")
CATALOG_FILE = os.path.join(SHARED_DATA_DIR, "day7_catalog.json")
RECIPES_FILE = os.path.join(SHARED_DATA_DIR, "day7_recipes.json")

ORDERS_DIR = os.path.join(BASE_DIR, "orders")
os.makedirs(ORDERS_DIR, exist_ok=True)

LATEST_ORDER_FILE = os.path.join(ORDERS_DIR, "day7_latest_order.json")


# ---------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------

@dataclass
class CatalogItem:
    id: int
    name: str
    category: str
    price: float
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CatalogItem":
        return cls(
            id=data["id"],
            name=data["name"],
            category=data.get("category", ""),
            price=float(data.get("price", 0)),
            tags=data.get("tags", []),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "price": self.price,
            "tags": self.tags,
        }


@dataclass
class CartItem:
    item: CatalogItem
    quantity: int

    def to_dict(self) -> dict:
        return {
            "id": self.item.id,
            "name": self.item.name,
            "category": self.item.category,
            "price": self.item.price,
            "quantity": self.quantity,
            "line_total": self.item.price * self.quantity,
        }


@dataclass
class Userdata:
    catalog: List[CatalogItem]
    recipes: Dict[str, List[str]]
    cart: List[CartItem] = field(default_factory=list)
    customer_name: str | None = None
    address: str | None = None
    session_start: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------
# HELPERS – LOAD CATALOG & RECIPES
# ---------------------------------------------------------

def load_catalog() -> List[CatalogItem]:
    if not os.path.exists(CATALOG_FILE):
        raise FileNotFoundError(f"Catalog JSON not found at {CATALOG_FILE}")

    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = [CatalogItem.from_dict(d) for d in data]
    logger.info("Loaded %d catalog items", len(items))
    return items


def load_recipes() -> Dict[str, List[str]]:
    if not os.path.exists(RECIPES_FILE):
        logger.warning("Recipes JSON not found at %s, using empty recipes", RECIPES_FILE)
        return {}

    with open(RECIPES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info("Loaded %d recipe mappings", len(data))
    # normalize keys to lower-case for matching
    return {k.lower(): v for k, v in data.items()}


def find_item_by_name(catalog: List[CatalogItem], name: str) -> CatalogItem | None:
    """Very simple name match: case-insensitive substring search."""
    name_lower = name.strip().lower()
    best_match = None
    best_score = 0

    for item in catalog:
        item_name = item.name.lower()
        # crude scoring by number of matching tokens
        score = 0
        for token in name_lower.split():
            if token in item_name:
                score += 1

        if score > best_score:
            best_score = score
            best_match = item

    return best_match


def get_cart_total(cart: List[CartItem]) -> float:
    return sum(ci.item.price * ci.quantity for ci in cart)


def save_order_to_json(userdata: Userdata) -> dict:
    """Build order payload and persist to JSON."""
    if not userdata.cart:
        raise ValueError("Cannot save order: cart is empty.")

    order_items = [ci.to_dict() for ci in userdata.cart]
    total = get_cart_total(userdata.cart)

    order = {
        "timestamp": datetime.now().isoformat(),
        "customer_name": userdata.customer_name or "Guest",
        "address": userdata.address or "Not provided",
        "items": order_items,
        "total": total,
    }

    with open(LATEST_ORDER_FILE, "w", encoding="utf-8") as f:
        json.dump(order, f, indent=4, ensure_ascii=False)

    logger.info("Saved latest order with %d items, total=%.2f", len(order_items), total)
    return order


# ---------------------------------------------------------
# TOOLS – CART & ORDER MANAGEMENT
# ---------------------------------------------------------

@function_tool
async def set_customer_name(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="Customer name for the order")],
) -> str:
    ctx.userdata.customer_name = name.strip()
    return f"Got it, I’ll place the order under the name {ctx.userdata.customer_name}."


@function_tool
async def add_item_to_cart(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="Name of the item to add, as spoken by the user")],
    quantity: Annotated[int, Field(description="How many units to add", ge=1)] = 1,
) -> str:
    catalog = ctx.userdata.catalog
    item = find_item_by_name(catalog, item_name)

    if not item:
        return (
            f"I couldn’t find an item matching '{item_name}' in the catalog. "
            "Please try a different name or ask what’s available."
        )

    # check if already in cart
    for ci in ctx.userdata.cart:
        if ci.item.id == item.id:
            ci.quantity += quantity
            break
    else:
        ctx.userdata.cart.append(CartItem(item=item, quantity=quantity))

    return f"Added {quantity} x {item.name} to your cart."


@function_tool
async def remove_item_from_cart(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="Name of the item to remove from cart")],
) -> str:
    name_lower = item_name.strip().lower()
    cart = ctx.userdata.cart

    if not cart:
        return "Your cart is currently empty."

    remaining: List[CartItem] = []
    removed_any = False

    for ci in cart:
        if name_lower in ci.item.name.lower():
            removed_any = True
            continue
        remaining.append(ci)

    ctx.userdata.cart = remaining

    if removed_any:
        return f"I’ve removed items matching '{item_name}' from your cart."
    else:
        return f"I couldn’t find any items matching '{item_name}' in your cart."


@function_tool
async def update_item_quantity(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="Name of the item in the cart")],
    quantity: Annotated[int, Field(description="New quantity (0 to remove)", ge=0)],
) -> str:
    name_lower = item_name.strip().lower()
    cart = ctx.userdata.cart

    if not cart:
        return "Your cart is currently empty."

    for ci in cart:
        if name_lower in ci.item.name.lower():
            if quantity == 0:
                cart.remove(ci)
                return f"I’ve removed {ci.item.name} from your cart."
            else:
                ci.quantity = quantity
                return f"I’ve updated {ci.item.name} to quantity {quantity}."

    return f"I couldn’t find any items matching '{item_name}' in your cart."


@function_tool
async def list_cart(ctx: RunContext[Userdata]) -> str:
    cart = ctx.userdata.cart
    if not cart:
        return "Your cart is currently empty."

    lines = []
    for ci in cart:
        line_total = ci.item.price * ci.quantity
        lines.append(f"{ci.quantity} x {ci.item.name} ({ci.item.price} each) = {line_total}")

    total = get_cart_total(cart)
    summary = "Here’s what is currently in your cart:\n" + "\n".join(lines) + f"\nTotal: {total}"
    return summary


@function_tool
async def add_ingredients_for_dish(
    ctx: RunContext[Userdata],
    dish_name: Annotated[str, Field(description="Dish name, e.g. 'peanut butter sandwich' or 'pasta'")],
) -> str:
    recipes = ctx.userdata.recipes
    catalog = ctx.userdata.catalog

    key = dish_name.strip().lower()
    if key not in recipes:
        return (
            f"I don’t have a recipe mapping for '{dish_name}' yet. "
            "You can still add individual items by name."
        )

    ingredient_names = recipes[key]
    added_items = []

    for ing in ingredient_names:
        item = find_item_by_name(catalog, ing)
        if item:
            # default quantity 1 per ingredient
            # if already in cart, increment
            for ci in ctx.userdata.cart:
                if ci.item.id == item.id:
                    ci.quantity += 1
                    break
            else:
                ctx.userdata.cart.append(CartItem(item=item, quantity=1))
            added_items.append(item.name)

    if not added_items:
        return (
            f"I tried to add ingredients for '{dish_name}', but none of the mapped items "
            "exist in the catalog. Please check your catalog and recipe mapping."
        )

    added_str = ", ".join(added_items)
    return f"For {dish_name}, I’ve added these to your cart: {added_str}."


@function_tool
async def place_order(ctx: RunContext[Userdata]) -> str:
    """
    Finalize the current cart as an order and save to JSON.
    """
    if not ctx.userdata.cart:
        return "Your cart is empty, so there’s nothing to place as an order."

    order = save_order_to_json(ctx.userdata)

    total = order["total"]
    item_count = len(order["items"])
    return (
        f"I’ve placed your order with {item_count} items. "
        f"Your total is {total}. The order has been saved to the system."
    )


# ---------------------------------------------------------
# AGENT – ORDERING ASSISTANT
# ---------------------------------------------------------

class FoodOrderingAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are a friendly food and grocery ordering assistant for a fictional brand called "QuickBasket".

Your goals:
- Help the user order groceries, snacks, and simple prepared foods.
- Manage a cart: add items, remove items, update quantities, list the cart.
- Support simple "ingredients for X" style requests using the `add_ingredients_for_dish` tool.
- When the user is done (they say things like "that's all", "place my order", "checkout"),
  confirm and then call `place_order`.

Behaviour:
- Greet the user and briefly explain: you can help them add groceries and simple meal ingredients.
- Ask clarifying questions when needed: quantity, which variant, etc. Keep questions short.
- Use the tools whenever the user talks about changing the cart or placing the order.
- Do NOT invent new items that are not in the catalog. If you are unsure, say you only know items from the catalog.
- If the user says something like "what's in my cart", call `list_cart`.
- For requests like "I need ingredients for a peanut butter sandwich", call `add_ingredients_for_dish`.
- Encourage the user to say "I'm done" or "place my order" when they are ready to checkout.

Tone:
- Warm, concise, and helpful.
- Mostly English. Light casual tone is okay, but stay clear and polite.
""",
            tools=[
                set_customer_name,
                add_item_to_cart,
                remove_item_from_cart,
                update_item_quantity,
                list_cart,
                add_ingredients_for_dish,
                place_order,
            ],
        )


# ---------------------------------------------------------
# PREWARM + ENTRYPOINT
# ---------------------------------------------------------

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["catalog"] = load_catalog()
    proc.userdata["recipes"] = load_recipes()


async def entrypoint(ctx: JobContext):
    catalog = ctx.proc.userdata.get("catalog") or load_catalog()
    recipes = ctx.proc.userdata.get("recipes") or load_recipes()

    userdata = Userdata(catalog=catalog, recipes=recipes)

    tts = murf.TTS(
        voice="en-US-matthew",  # Murf Falcon voice name can go here if configured
        style="Conversation",
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

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent):
        usage_collector.collect(ev.metrics)

    await session.start(
        agent=FoodOrderingAgent(),
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
