import os
import asyncio
import datetime

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from pymongo import MongoClient, DESCENDING

# Import the new "get_inventory" function from fetch.py
from fetch import get_inventory

load_dotenv()

TOKEN = os.getenv("TOKEN")
KIOSK_CHANNEL = os.getenv("KIOSK_CHANNEL")

# Connect to MongoDB on port 27018 (inside Docker Compose)
mongo_client = MongoClient("mongodb://mongodb:27018")
db = mongo_client["kiosk_db"]
collection = db["inventory_changes"]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Keep track of the last known inventory in memory
old_inventory = {}


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    print(f"ID: {bot.user.id}")
    print(f"Guilds: {len(bot.guilds)}")

    channel = bot.get_channel(int(KIOSK_CHANNEL))
    if channel:
        await channel.send("Lytter på kjøp i kiosken...")

    # Start the background task that checks for kiosk changes
    check_kiosk_changes.start()


@tasks.loop(minutes=0.15)  # ~9 seconds
async def check_kiosk_changes():
    """
    Periodically polls the kiosk site for updated product counts,
    logs changes in MongoDB, and sends a Discord embed per product.
    """
    global old_inventory

    try:
        new_inventory = get_inventory()
    except Exception as e:
        print(f"Error fetching inventory: {e}")
        return

    if not new_inventory:
        print("No inventory found or fetch failed.")
        return

    # Determine which products changed
    changes = []
    for product, new_count in new_inventory.items():
        old_count = old_inventory.get(product)
        if old_count is None:
            # We didn't track this product before
            if new_count > 0:
                changes.append((product, None, new_count))
        else:
            if old_count != new_count:
                changes.append((product, old_count, new_count))

    # Update our local snapshot
    old_inventory = new_inventory

    # If there are changes, send an embed for each changed product
    if changes:
        kiosk_channel = bot.get_channel(int(KIOSK_CHANNEL))
        if not kiosk_channel:
            print("Could not find kiosk channel, not sending embed.")
            return

        for (product, old_count, new_count) in changes:
            if old_count is None:
                # New product
                purchased = new_count
                description = (
                    f"Nytt produkt registrert: **{product}**! "
                    f"Antall kjøpt nå: {purchased} stk"
                )
            else:
                # Calculate how many were purchased
                purchased = new_count - old_count
                if purchased > 0:
                    description = (
                        f"Nytt kjøp av **{product}**! "
                        f"Antall kjøpt nå: {purchased} stk"
                        f"\nTotalt antal kjøpt: {new_count} stk"
                    )
                else:
                    # If purchased <= 0, might be a rare "count decreased" scenario
                    pass

            embed = discord.Embed(
                title="Nytt kjøp i kiosken!",
                description=description,
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow(),
            )

            # Insert each change into MongoDB
            record = {
                "product": product,
                "count": new_count,
                "timestamp": datetime.datetime.utcnow(),
            }
            collection.insert_one(record)

            # Send one embed per changed product
            await kiosk_channel.send(embed=embed)
    else:
        print("No changes detected this run.")


@bot.command(name="summary24")
async def summary_24h(ctx):
    """
    A command that creates ONE embed showing how many items
    have been sold for each product in the LAST 24 hours.
    Usage: !summary24
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)

    # Get all distinct products from the changes collection
    products = collection.distinct("product")

    lines = []
    for product in products:
        # 1) Find the record just before or at the 24h cutoff (the "old" baseline)
        old_doc = collection.find_one(
            {"product": product, "timestamp": {"$lte": cutoff}},
            sort=[("timestamp", DESCENDING)],
        )

        # 2) Find the latest record overall (the "new" final)
        new_doc = collection.find_one(
            {"product": product}, sort=[("timestamp", DESCENDING)]
        )

        # If we have no record at all for some reason, skip
        if not new_doc:
            continue

        old_count = old_doc["count"] if old_doc else 0
        new_count = new_doc["count"]

        # Items sold in the last 24 hours
        sold_24h = new_count - old_count
        lines.append(f"**{product}**: {sold_24h} solgt siste 24 timer")

    # Build the single summary embed
    if lines:
        summary = "\n".join(lines)
    else:
        summary = "Ingen produkter funnet i databasen eller ingen salg registrert."

    embed = discord.Embed(
        title="Salg siste 24 timer",
        description=summary,
        color=discord.Color.blue(),
        timestamp=datetime.datetime.utcnow(),
    )

    await ctx.send(embed=embed)


if __name__ == "__main__":
    bot.run(TOKEN)
