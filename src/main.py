import os
import asyncio
import datetime

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from pymongo import MongoClient

# Import the new "get_inventory" function
from fetch import get_inventory

load_dotenv()

TOKEN = os.getenv("TOKEN")
KIOSK_CHANNEL = os.getenv("KIOSK_CHANNEL")

# If using Docker Compose with a 'mongodb' service name, do:
# Locally, you might use "localhost"
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

    # Optionally announce the bot is ready in the kiosk channel
    channel = bot.get_channel(int(KIOSK_CHANNEL))
    if channel:
        await channel.send("Lytter på kjøp i kiosken...")

    # Start the background task
    check_kiosk_changes.start()


@tasks.loop(minutes=0.15)  # ~9 seconds
async def check_kiosk_changes():
    global old_inventory

    try:
        new_inventory = get_inventory()
    except Exception as e:
        print(f"Error fetching inventory: {e}")
        return

    if not new_inventory:
        print("No inventory found or fetch failed.")
        return

    changes = []
    for product, new_count in new_inventory.items():
        old_count = old_inventory.get(product)
        if old_count is None:
            # Product wasn't tracked before; treat the entire new_count as purchased
            if new_count > 0:
                changes.append((product, None, new_count))
        else:
            if old_count != new_count:
                changes.append((product, old_count, new_count))

    old_inventory = new_inventory

    if changes:
        kiosk_channel = bot.get_channel(int(KIOSK_CHANNEL))
        if not kiosk_channel:
            print("Could not find kiosk channel, not sending embed.")
            return

        for (product, old_count, new_count) in changes:
            # If old_count is None, it's a brand new product
            if old_count is None:
                purchased = new_count
                description = (
                    f"En person kjøpte "
                    f"{purchased} stk **{product}**!"
                )
            else:
                # Calculate how many were bought since last time
                purchased = new_count - old_count
                if purchased > 0:
                    description = (
                        f"Nytt produkt: **{product}**! "
                        f" antall kjøpt: {new_count} stk"
                    )
                else:
                    # If purchased <= 0, it might mean the count went down (which is unusual),
                    # but we'll still note it
                    purchased = abs(purchased)
                    description = (
                        f"({purchased} stk {product} mindre solgt enn sist?) "
                        f"Kan være en feil eller retur..."
                    )

            # Build a single embed for this product
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


if __name__ == "__main__":
    bot.run(TOKEN)
