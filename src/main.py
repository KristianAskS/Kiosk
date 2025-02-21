import os
import asyncio
import datetime

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from pymongo import MongoClient, DESCENDING

from fetch import get_inventory

load_dotenv()

TOKEN = os.getenv("TOKEN")
KIOSK_CHANNEL = os.getenv("KIOSK_CHANNEL")

mongo_client = MongoClient("mongodb://mongodb:27018")
db = mongo_client["kiosk_db"]
# Rename collection to reflect "events" or "purchases"
events_collection = db["inventory_events"]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Keep track of the last known kiosk "counts" in memory
old_inventory = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    print(f"ID: {bot.user.id}")
    print(f"Guilds: {len(bot.guilds)}")

    channel = bot.get_channel(int(KIOSK_CHANNEL))
    if channel:
        await channel.send("Lytter på kjøp i kiosken...")

    # Start the background task
    check_kiosk_changes.start()

@tasks.loop(minutes=0.15)  # ~9 seconds
async def check_kiosk_changes():
    """
    Poll the kiosk site for updated product counts.
    If a product's count goes up, record that 'delta' in DB
    and send a purchase embed. If difference > 20, skip it (unrealistic).
    """
    global old_inventory

    try:
        new_inventory = get_inventory()  # e.g. { "Pepsi Max 0.5l": 552, ... }
    except Exception as e:
        print(f"Error fetching inventory: {e}")
        return

    if not new_inventory:
        print("No inventory found or fetch failed.")
        return

    # Check each product in new_inventory
    for product, new_count in new_inventory.items():
        old_count = old_inventory.get(product)

        # If we have no old_count in memory, try DB
        if old_count is None:
            last_doc = events_collection.find_one(
                {"product": product},
                sort=[("timestamp", DESCENDING)]
            )
            if last_doc:
                # This doc stored the last known kiosk count
                old_count = last_doc.get("kiosk_count", 0)
            else:
                old_count = 0

        # Compare
        delta = new_count - old_count
        if delta > 0:
            # Normal purchase scenario
            # Skip if the jump is "unrealistic" (> 20)
            if delta > 20:
                print(f"Skipping unrealistic jump for {product}: {delta} items.")
                old_inventory[product] = new_count
                continue

            # Record event in DB
            record = {
                "product": product,
                "delta": delta,           # How many just bought
                "kiosk_count": new_count, # The new total as reported
                "timestamp": datetime.datetime.utcnow()
            }
            events_collection.insert_one(record)

            # Send embed to channel
            kiosk_channel = bot.get_channel(int(KIOSK_CHANNEL))
            if kiosk_channel:
                description = (
                    f"Nytt kjøp av **{product}**!\n"
                    f"Økning på {delta} stk\n"
                    f"Totalt antall kjøpt: {new_count}"
                )
                embed = discord.Embed(
                    title="Nytt kjøp i kiosken!",
                    description=description,
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.utcnow(),
                )
                await kiosk_channel.send(embed=embed)

        elif delta < 0:
            # Count went down (possible returns or correction)
            print(f"Count for {product} decreased by {-delta}, ignoring.")
            # Do not store or embed if we want to ignore negative
            pass

        # Update memory so next check is correct
        old_inventory[product] = new_count

@bot.command(name="summary24")
async def summary_24h(ctx):
    """
    Sums how many items were actually purchased (sum of 'delta')
    in the last 24 hours for each product.
    Usage: !summary24
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)

    # pipeline grouping by product, summing delta for docs after 'cutoff'
    pipeline = [
        {"$match": {"timestamp": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$product",
            "total_sold": {"$sum": "$delta"}
        }}
    ]

    results = list(events_collection.aggregate(pipeline))
    if not results:
        await ctx.send(embed=discord.Embed(
            title="Salg siste 24 timer",
            description="Ingen produkter funnet i databasen eller ingen salg registrert.",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        ))
        return

    lines = []
    for doc in results:
        product = doc["_id"]
        total_sold = doc["total_sold"]
        lines.append(f"**{product}**: {total_sold} solgt siste 24 timer")

    summary = "\n".join(lines)
    embed = discord.Embed(
        title="Salg siste 24 timer",
        description=summary,
        color=discord.Color.blue(),
        timestamp=datetime.datetime.utcnow(),
    )
    await ctx.send(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)