import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from rooms import RoomManager, VoiceRoomsCog

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Ошибка: переменная DISCORD_TOKEN не задана. Скопируйте .env.example в .env и укажите токен.")

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
manager = RoomManager(bot)


@bot.event
async def on_ready():
    print(f"Бот {bot.user} запущен (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Слеш-команд синхронизировано: {len(synced)}")
    except Exception as exc:
        print(f"Ошибка синхронизации команд: {exc}")


async def main():
    await bot.add_cog(VoiceRoomsCog(bot, manager))
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
