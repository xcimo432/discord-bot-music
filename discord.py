DISCORD_TOKEN=MTUzNzE0NzA1MzI1NDI1NDY5Mg.Gk1rlI.swwCZR3SzmJl4k4pkulz_y43YWCXIzcpTfy8AQ
.env
__pycache__/
data/
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
discord.py>=2.3.2
python-dotenv>=1.0.0
import asyncio
import json
import random
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

CATEGORY_NAME = "Приватные комнаты"
DATA_FILE = Path(__file__).parent / "data" / "rooms.json"

GREEN = 0x57F287
RED = 0xED4245
GREY = 0x2B2D31

OWNER_OW = discord.PermissionOverwrite(
    view_channel=True,
    connect=True,
    speak=True,
    stream=True,
    use_voice_activation=True,
    manage_channels=True,
    manage_permissions=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)
MEMBER_OW = discord.PermissionOverwrite(
    view_channel=True,
    connect=True,
    speak=True,
    stream=True,
    use_voice_activation=True,
)
EVERYONE_OW = discord.PermissionOverwrite(
    view_channel=True,
    connect=False,
)
HIDDEN_OW = discord.PermissionOverwrite(
    view_channel=False,
    connect=False,
)


class Room:
    __slots__ = ("channel_id", "owner_id", "role_id", "permanent")

    def __init__(self, channel_id: int, owner_id: int, role_id: int, permanent: bool = False):
        self.channel_id = channel_id
        self.owner_id = owner_id
        self.role_id = role_id
        self.permanent = permanent

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "owner_id": self.owner_id,
            "role_id": self.role_id,
            "permanent": self.permanent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Room":
        return cls(data["channel_id"], data["owner_id"], data["role_id"], data.get("permanent", False))


class RoomManager:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rooms: dict[int, Room] = {}
        self._load()

    def _load(self):
        if not DATA_FILE.exists():
            return
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for channel_id, data in raw.items():
            self.rooms[int(channel_id)] = Room.from_dict(data)

    def _save(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        raw = {str(rid): room.to_dict() for rid, room in self.rooms.items()}
        DATA_FILE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_room(self, channel_id: int) -> Room | None:
        return self.rooms.get(channel_id)

    def get_owner_room(self, owner_id: int) -> Room | None:
        for room in self.rooms.values():
            if room.owner_id == owner_id:
                return room
        return None

    async def create_room(self, member: discord.Member) -> tuple[Room, discord.VoiceChannel]:
        guild = member.guild
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(CATEGORY_NAME)

        base = f"Комната {member.display_name}"
        name, i = base, 1
        while discord.utils.get(guild.voice_channels, name=name):
            i += 1
            name = f"{base} #{i}"

        role = await guild.create_role(
            name=f"🎙 {member.display_name}",
            color=discord.Color.random(),
            hoist=False,
            mentionable=False,
        )

        overwrites = {
            guild.default_role: EVERYONE_OW,
            role: MEMBER_OW,
            member: OWNER_OW,
        }
        channel = await guild.create_voice_channel(name, category=category, overwrites=overwrites)
        await member.add_roles(role, reason="Владелец приватной комнаты")

        room = Room(channel.id, member.id, role.id)
        self.rooms[channel.id] = room
        self._save()
        return room, channel

    async def delete_room(self, room: Room):
        self.rooms.pop(room.channel_id, None)
        self._save()
        channel = self.bot.get_channel(room.channel_id)
        role = None
        if channel is not None:
            role = channel.guild.get_role(room.role_id)
            try:
                await channel.delete(reason="Приватная комната удалена")
            except discord.HTTPException:
                pass
        if role is not None:
            try:
                for m in list(role.members):
                    try:
                        await m.remove_roles(role, reason="Комната удалена")
                    except discord.HTTPException:
                        pass
                await role.delete(reason="Комната удалена")
            except discord.HTTPException:
                pass

    async def add_member_role(self, member: discord.Member, room: Room):
        role = member.guild.get_role(room.role_id)
        if role is not None and role not in member.roles:
            try:
                await member.add_roles(role, reason="Доступ к приватной комнате")
            except discord.HTTPException:
                pass

    async def remove_member_role(self, member: discord.Member, room: Room):
        role = member.guild.get_role(room.role_id)
        if role is not None and role in member.roles:
            try:
                await member.remove_roles(role, reason="Покинул приватную комнату")
            except discord.HTTPException:
                pass


class TargetModal(discord.ui.Modal):
    def __init__(self, title: str, label: str, placeholder: str, handler, success_msg: str):
        super().__init__(title=title)
        self.handler = handler
        self.success_msg = success_msg
        self.add_item(discord.ui.TextInput(label=label, placeholder=placeholder, required=True, max_length=64))

    async def on_submit(self, interaction: discord.Interaction):
        await self.handler(interaction, self.children[0].value, self.success_msg)


class LimitModal(discord.ui.Modal):
    def __init__(self, handler, success_msg: str):
        super().__init__(title="🔢 Лимит участников")
        self.handler = handler
        self.success_msg = success_msg
        self.add_item(discord.ui.TextInput(label="Число участников (0 = без лимита)", placeholder="10", max_length=2, required=True))

    async def on_submit(self, interaction: discord.Interaction):
        await self.handler(interaction, self.children[0].value, self.success_msg)


class RenameModal(discord.ui.Modal):
    def __init__(self, handler, success_msg: str):
        super().__init__(title="✏️ Переименовать комнату")
        self.handler = handler
        self.success_msg = success_msg
        self.add_item(discord.ui.TextInput(label="Новое название", placeholder="Моя комната", min_length=1, max_length=100, required=True))

    async def on_submit(self, interaction: discord.Interaction):
        await self.handler(interaction, self.children[0].value, self.success_msg)


class PanelView(discord.ui.View):
    def __init__(self, cog: "VoiceRoomsCog", owner_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.owner_id = owner_id

    async def _resolve(self, interaction: discord.Interaction):
        if not (interaction.user.voice and interaction.user.voice.channel):
            await interaction.response.send_message("❌ Зайдите в свою голосовую комнату, чтобы управлять ею.", ephemeral=True)
            return None
        room = self.cog.manager.get_room(interaction.user.voice.channel.id)
        if room is None or room.owner_id != interaction.user.id:
            await interaction.response.send_message("❌ Это не ваша приватная комната.", ephemeral=True)
            return None
        return room

    @discord.ui.button(label="🟢 Открыть", style=discord.ButtonStyle.success, row=0)
    async def open_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await self.cog._open_room(interaction, interaction.user.voice.channel)

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger, row=0)
    async def close_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await self.cog._close_room(interaction, interaction.user.voice.channel)

    @discord.ui.button(label="👁 Скрыть", style=discord.ButtonStyle.secondary, row=0)
    async def hide_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await self.cog._hide_room(interaction, interaction.user.voice.channel)

    @discord.ui.button(label="👀 Показать", style=discord.ButtonStyle.secondary, row=0)
    async def show_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await self.cog._show_room(interaction, interaction.user.voice.channel)

    @discord.ui.button(label="🔢 Лимит", style=discord.ButtonStyle.primary, row=1)
    async def limit_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(LimitModal(self.cog._limit_target, "🔵 Лимит участников установлен на {n}."))

    @discord.ui.button(label="✏️ Имя", style=discord.ButtonStyle.primary, row=1)
    async def rename_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(RenameModal(self.cog._rename_target, "✏️ Комната переименована в «{name}»."))

    @discord.ui.button(label="📢 Мут", style=discord.ButtonStyle.secondary, row=1)
    async def mute_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(TargetModal("🔇 Забрать микрофон", "Кого замутить?", "@user или имя", self.cog._mute_target, "🔵 @{name} — микрофон отключён."))

    @discord.ui.button(label="🔊 Анмут", style=discord.ButtonStyle.secondary, row=1)
    async def unmute_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(TargetModal("🔊 Вернуть микрофон", "Кому включить микрофон?", "@user или имя", self.cog._unmute_target, "🟣 @{name} — микрофон включён."))

    @discord.ui.button(label="➕ Разрешить", style=discord.ButtonStyle.success, row=2)
    async def allow_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(TargetModal("✅ Выдать доступ", "Кому выдать доступ?", "@user или имя", self.cog._allow_target, "✅ @{name} получил доступ к комнате."))

    @discord.ui.button(label="➖ Запретить", style=discord.ButtonStyle.danger, row=2)
    async def deny_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(TargetModal("🔴 Забрать доступ", "У кого забрать доступ?", "@user или имя", self.cog._deny_target, "🔴 У @{name} отобран доступ."))

    @discord.ui.button(label="🚪 Кик", style=discord.ButtonStyle.danger, row=2)
    async def kick_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(TargetModal("⚪ Выгнать", "Кого выгнать?", "@user или имя", self.cog._kick_target, "⚪ @{name} выгнан из комнаты."))

    @discord.ui.button(label="👑 Передать", style=discord.ButtonStyle.primary, row=2)
    async def transfer_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await interaction.response.send_modal(TargetModal("👑 Передать владельца", "Кому передать владение?", "@user или имя", self.cog._transfer_target, "👑 @{name} теперь владелец комнаты."))

    @discord.ui.button(label="♾️ Постоянность", style=discord.ButtonStyle.secondary, row=3)
    async def permanent_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await self.cog._toggle_permanent(interaction, room)

    @discord.ui.button(label="🗑 Удалить", style=discord.ButtonStyle.danger, row=3)
    async def delete_btn(self, interaction, _):
        room = await self._resolve(interaction)
        if not room:
            return
        await self.cog._delete_room(interaction, room)


class VoiceRoomsCog(commands.Cog, name="Приватные комнаты"):
    def __init__(self, bot: commands.Bot, manager: RoomManager):
        self.bot = bot
        self.manager = manager
        self._delete_tasks: dict[int, asyncio.Task] = {}

    # ---------- helpers ----------
    def _resolve_member(self, guild: discord.Guild, text: str) -> discord.Member | None:
        text = text.strip()
        if text.isdigit():
            m = guild.get_member(int(text))
            if m:
                return m
        if text.startswith("<@") and text.endswith(">"):
            uid = text.strip("<@!>")
            if uid.isdigit():
                m = guild.get_member(int(uid))
                if m:
                    return m
        for m in guild.members:
            if m.display_name == text or m.name == text or (m.nick or "") == text:
                return m
        return None

    def _target_ok(self, member: discord.Member, room: Room) -> bool:
        channel = self.bot.get_channel(room.channel_id)
        return channel is not None and member.voice is not None and member.voice.channel is not None and member.voice.channel.id == room.channel_id

    async def _reply_success(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(embed=discord.Embed(description=text, color=GREEN), ephemeral=True)

    async def _reply_error(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(embed=discord.Embed(description=text, color=RED), ephemeral=True)

    async def send_panel(self, member: discord.Member, room: Room):
        channel = self.bot.get_channel(room.channel_id)
        name = channel.name if channel else "Комната"
        em = discord.Embed(
            title="🎛 Панель управления комнатой",
            description=f"Управляйте комнатой **«{name}»** кнопками ниже или слеш-командами — полный список в **/help**.",
            color=GREY,
        )
        view = PanelView(self, room.owner_id)
        try:
            dm = await member.create_dm()
            await dm.send(embed=em, view=view)
        except discord.HTTPException:
            pass

    # ---------- slash: create / panel / help ----------
    @app_commands.command(name="create", description="Создать новую приватную голосовую комнату")
    async def create(self, interaction: discord.Interaction):
        existing = self.manager.get_owner_room(interaction.user.id)
        if existing:
            ch = self.bot.get_channel(existing.channel_id)
            name = ch.name if ch else "Комната"
            await self._reply_error(interaction, f"❌ У вас уже есть комната «{name}».")
            return
        room, channel = await self.manager.create_room(interaction.user)
        if interaction.user.voice and interaction.user.voice.channel:
            try:
                await interaction.user.move_to(channel)
            except discord.HTTPException:
                pass
        await self._reply_success(
            interaction,
            f"✅ Создан голосовой канал «**{channel.name}**». Вы — владелец. Используйте **/help** для управления.",
        )
        await self.send_panel(interaction.user, room)

    @app_commands.command(name="panel", description="Показать панель управления комнатой (кнопки)")
    async def panel(self, interaction: discord.Interaction):
        room = self.manager.get_owner_room(interaction.user.id)
        if room is None:
            await self._reply_error(interaction, "❌ У вас нет приватной комнаты. Создайте её командой **/create**.")
            return
        await self.send_panel(interaction.user, room)
        await self._reply_success(interaction, "✅ Панель управления отправлена вам в личные сообщения.")

    @app_commands.command(name="help", description="Список всех команд комнаты")
    async def help_cmd(self, interaction: discord.Interaction):
        text = (
            "**🎮 Управление комнатой** (только владелец, из своего голосового канала)\n"
            "🔵 `/limit 10` — лимит участников\n"
            "🟠 `/close` — закрыть вход\n"
            "🟡 `/open` — открыть вход\n"
            "🔴 `/deny @user` — забрать доступ\n"
            "✅ `/allow @user` — выдать доступ\n"
            "✏️ `/rename имя` — переименовать\n"
            "👑 `/transfer @user` — передать владельца\n"
            "⚪ `/kick @user` — выгнать из комнаты\n"
            "📢 `/mute @user` — отключить микрофон\n"
            "🔊 `/unmute @user` — включить микрофон\n"
            "👁 `/hide` — скрыть из списка\n"
            "👀 `/show` — показать\n"
            "♾️ `/permanent` — переключить постоянную комнату (не удаляется при пустоте)\n"
            "🗑 `/delete` — удалить комнату\n\n"
            "**🔧 Общие команды**\n"
            "➕ `/create` — создать комнату\n"
            "🎛 `/panel` — кнопки управления в ЛС\n"
            "❔ `/help` — этот список"
        )
        await interaction.response.send_message(embed=discord.Embed(title="📖 Команды бота", description=text, color=GREY), ephemeral=True)

    # ---------- slash: room commands ----------
    def _channel_for(self, interaction: discord.Interaction):
        if not (interaction.user.voice and interaction.user.voice.channel):
            return None, "❌ Вы не находитесь в голосовом канале. Зайдите в комнату, которой хотите управлять."
        room = self.manager.get_room(interaction.user.voice.channel.id)
        if room is None:
            return None, "❌ Это не приватная комната."
        if room.owner_id != interaction.user.id:
            return None, "❌ Только владелец комнаты может выполнять эти команды."
        return room, None

    @app_commands.command(name="limit", description="Установить лимит участников комнаты")
    @app_commands.describe(number="Максимум участников (0 = без лимита)")
    async def limit(self, interaction: discord.Interaction, number: app_commands.Range[int, 0, 99]):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await interaction.user.voice.channel.edit(user_limit=None if number == 0 else number)
        await self._reply_success(interaction, f"🔵 Лимит участников установлен на **{number}**." if number else "🔵 Лимит участников снят.")

    @app_commands.command(name="close", description="Закрыть комнату (запретить вход)")
    async def close(self, interaction: discord.Interaction):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await self._close_room(interaction, interaction.user.voice.channel)

    @app_commands.command(name="open", description="Открыть комнату (разрешить вход)")
    async def open_cmd(self, interaction: discord.Interaction):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await self._open_room(interaction, interaction.user.voice.channel)

    @app_commands.command(name="hide", description="Скрыть комнату из списка каналов")
    async def hide(self, interaction: discord.Interaction):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await self._hide_room(interaction, interaction.user.voice.channel)

    @app_commands.command(name="show", description="Сделать комнату видимой")
    async def show(self, interaction: discord.Interaction):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await self._show_room(interaction, interaction.user.voice.channel)

    @app_commands.command(name="allow", description="Выдать доступ к комнате")
    async def allow(self, interaction: discord.Interaction, user: discord.Member):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        if user.id == room.owner_id:
            await self._reply_error(interaction, "❌ Владелец и так имеет доступ.")
            return
        await self._allow_impl(interaction, interaction.user.voice.channel, room, user)

    @app_commands.command(name="deny", description="Забрать доступ к комнате")
    async def deny(self, interaction: discord.Interaction, user: discord.Member):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        if user.id == room.owner_id:
            await self._reply_error(interaction, "❌ Нельзя забрать доступ у владельца.")
            return
        await self._deny_impl(interaction, interaction.user.voice.channel, room, user)

    @app_commands.command(name="rename", description="Переименовать комнату")
    @app_commands.describe(name="Новое название")
    async def rename(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 100]):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await interaction.user.voice.channel.edit(name=name)
        await self._reply_success(interaction, f"✏️ Комната переименована в «**{name}**».")

    @app_commands.command(name="transfer", description="Передать владение комнатой другому пользователю")
    async def transfer(self, interaction: discord.Interaction, user: discord.Member):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        if user.id == room.owner_id:
            await self._reply_error(interaction, "❌ Вы уже владеете этой комнатой.")
            return
        channel = interaction.user.voice.channel
        await channel.set_permissions(user, overwrite=OWNER_OW)
        await channel.set_permissions(interaction.user, overwrite=MEMBER_OW)
        await self.manager.add_member_role(user, room)
        room.owner_id = user.id
        self.manager._save()
        await self._reply_success(interaction, f"👑 **{user.display_name}** теперь владелец комнаты.")
        if user.voice and user.voice.channel and user.voice.channel.id == room.channel_id:
            await self.send_panel(user, room)

    @app_commands.command(name="kick", description="Выгнать пользователя из комнаты")
    async def kick(self, interaction: discord.Interaction, user: discord.Member):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        if user.id == room.owner_id:
            await self._reply_error(interaction, "❌ Нельзя выгнать владельца комнаты.")
            return
        if not self._target_ok(user, room):
            await self._reply_error(interaction, "❌ Пользователь не находится в вашей комнате.")
            return
        try:
            await user.move_to(None)
        except discord.HTTPException:
            await self._reply_error(interaction, "❌ Не удалось выгнать пользователя.")
            return
        await self._reply_success(interaction, f"⚪ **{user.display_name}** выгнан из комнаты.")

    @app_commands.command(name="mute", description="Отключить микрофон пользователю в комнате")
    async def mute(self, interaction: discord.Interaction, user: discord.Member):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        if user.id == room.owner_id:
            await self._reply_error(interaction, "❌ Нельзя замутить владельца комнаты.")
            return
        if not self._target_ok(user, room):
            await self._reply_error(interaction, "❌ Пользователь не находится в вашей комнате.")
            return
        await user.edit(mute=True)
        await self._reply_success(interaction, f"🔵 **{user.display_name}** — микрофон отключён.")

    @app_commands.command(name="unmute", description="Включить микрофон пользователю в комнате")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        if not self._target_ok(user, room):
            await self._reply_error(interaction, "❌ Пользователь не находится в вашей комнате.")
            return
        await user.edit(mute=False)
        await self._reply_success(interaction, f"🟣 **{user.display_name}** — микрофон включён.")

    @app_commands.command(name="permanent", description="Включить/выключить постоянную комнату (не удаляется при пустоте)")
    async def permanent(self, interaction: discord.Interaction):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await self._toggle_permanent(interaction, room)

    @app_commands.command(name="delete", description="Удалить комнату")
    async def delete(self, interaction: discord.Interaction):
        room, err = self._channel_for(interaction)
        if err:
            await self._reply_error(interaction, err)
            return
        await self._delete_room(interaction, room)

    # ---------- shared workers ----------
    async def _open_room(self, interaction, channel):
        await channel.set_permissions(channel.guild.default_role, overwrite=discord.PermissionOverwrite(connect=True, view_channel=True))
        await self._reply_success(interaction, "🟡 Комната открыта. Вход разрешён.")

    async def _close_room(self, interaction, channel):
        await channel.set_permissions(channel.guild.default_role, overwrite=EVERYONE_OW)
        await self._reply_success(interaction, "🟠 Комната закрыта. Вход запрещён.")

    async def _hide_room(self, interaction, channel):
        await channel.set_permissions(channel.guild.default_role, overwrite=HIDDEN_OW)
        await self._reply_success(interaction, "🔵 Комната скрыта из списка каналов.")

    async def _show_room(self, interaction, channel):
        await channel.set_permissions(channel.guild.default_role, overwrite=EVERYONE_OW)
        await self._reply_success(interaction, "👀 Комната снова видима.")

    async def _toggle_permanent(self, interaction, room):
        room.permanent = not room.permanent
        self.manager._save()
        state = "постоянной (не удалится при пустоте)" if room.permanent else "временной (удалится, когда все уйдут)"
        await self._reply_success(interaction, f"♾️ Комната теперь {state}.")

    async def _delete_room(self, interaction, room):
        self._cancel_delete(room)
        await self.manager.delete_room(room)
        await self._reply_success(interaction, "🗑 Комната удалена.")

    async def _allow_impl(self, interaction, channel, room, member):
        await channel.set_permissions(member, overwrite=discord.PermissionOverwrite(connect=True, view_channel=True, speak=True, stream=True, use_voice_activation=True))
        await self.manager.add_member_role(member, room)
        await self._reply_success(interaction, f"✅ **{member.display_name}** получил доступ к комнате.")

    async def _deny_impl(self, interaction, channel, room, member):
        if member.voice and member.voice.channel and member.voice.channel.id == room.channel_id:
            try:
                await member.move_to(None)
            except discord.HTTPException:
                pass
        await self.manager.remove_member_role(member, room)
        await channel.set_permissions(member, overwrite=discord.PermissionOverwrite(view_channel=False, connect=False, speak=False))
        await self._reply_success(interaction, f"🔴 У **{member.display_name}** отобран доступ.")

    async def _limit_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        try:
            n = int(raw.strip())
        except ValueError:
            await self._reply_error(interaction, "❌ Введите число (0 = без лимита).")
            return
        if n < 0 or n > 99:
            await self._reply_error(interaction, "❌ Лимит должен быть от 0 до 99.")
            return
        channel = self.bot.get_channel(room.channel_id)
        await channel.edit(user_limit=None if n == 0 else n)
        await self._reply_success(interaction, "🔵 Лимит участников установлен на **%d**." % n if n else "🔵 Лимит участников снят.")

    async def _rename_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        name = raw.strip()
        channel = self.bot.get_channel(room.channel_id)
        await channel.edit(name=name)
        await self._reply_success(interaction, f"✏️ Комната переименована в «**{name}**».")

    async def _kick_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        member = self._resolve_member(interaction.guild, raw)
        if member is None:
            await self._reply_error(interaction, "❌ Пользователь не найден.")
            return
        if member.id == room.owner_id:
            await self._reply_error(interaction, "❌ Нельзя выгнать владельца.")
            return
        if not self._target_ok(member, room):
            await self._reply_error(interaction, "❌ Пользователь не находится в вашей комнате.")
            return
        try:
            await member.move_to(None)
        except discord.HTTPException:
            await self._reply_error(interaction, "❌ Не удалось выгнать пользователя.")
            return
        await self._reply_success(interaction, f"⚪ **{member.display_name}** выгнан из комнаты.")

    async def _mute_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        member = self._resolve_member(interaction.guild, raw)
        if member is None:
            await self._reply_error(interaction, "❌ Пользователь не найден.")
            return
        if member.id == room.owner_id:
            await self._reply_error(interaction, "❌ Нельзя замутить владельца.")
            return
        if not self._target_ok(member, room):
            await self._reply_error(interaction, "❌ Пользователь не находится в вашей комнате.")
            return
        await member.edit(mute=True)
        await self._reply_success(interaction, f"🔵 **{member.display_name}** — микрофон отключён.")

    async def _unmute_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        member = self._resolve_member(interaction.guild, raw)
        if member is None:
            await self._reply_error(interaction, "❌ Пользователь не найден.")
            return
        if not self._target_ok(member, room):
            await self._reply_error(interaction, "❌ Пользователь не находится в вашей комнате.")
            return
        await member.edit(mute=False)
        await self._reply_success(interaction, f"🟣 **{member.display_name}** — микрофон включён.")

    async def _allow_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        member = self._resolve_member(interaction.guild, raw)
        if member is None:
            await self._reply_error(interaction, "❌ Пользователь не найден.")
            return
        if member.id == room.owner_id:
            await self._reply_error(interaction, "❌ Владелец и так имеет доступ.")
            return
        channel = self.bot.get_channel(room.channel_id)
        await self._allow_impl(interaction, channel, room, member)

    async def _deny_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        member = self._resolve_member(interaction.guild, raw)
        if member is None:
            await self._reply_error(interaction, "❌ Пользователь не найден.")
            return
        if member.id == room.owner_id:
            await self._reply_error(interaction, "❌ Нельзя забрать доступ у владельца.")
            return
        channel = self.bot.get_channel(room.channel_id)
        await self._deny_impl(interaction, channel, room, member)

    async def _transfer_target(self, interaction, raw, success_msg):
        room = self._modal_room(interaction)
        if room is None:
            await self._reply_error(interaction, "❌ Зайдите в свою комнату или подтвердите права владельца.")
            return
        member = self._resolve_member(interaction.guild, raw)
        if member is None:
            await self._reply_error(interaction, "❌ Пользователь не найден.")
            return
        if member.id == room.owner_id:
            await self._reply_error(interaction, "❌ Вы уже владеете этой комнатой.")
            return
        channel = self.bot.get_channel(room.channel_id)
        await channel.set_permissions(member, overwrite=OWNER_OW)
        await channel.set_permissions(interaction.user, overwrite=MEMBER_OW)
        await self.manager.add_member_role(member, room)
        room.owner_id = member.id
        self.manager._save()
        await self._reply_success(interaction, f"👑 **{member.display_name}** теперь владелец комнаты.")
        if member.voice and member.voice.channel and member.voice.channel.id == room.channel_id:
            await self.send_panel(member, room)

    def _modal_room(self, interaction) -> Room | None:
        if not (interaction.user.voice and interaction.user.voice.channel):
            return None
        room = self.manager.get_room(interaction.user.voice.channel.id)
        if room is None or room.owner_id != interaction.user.id:
            return None
        return room

    # ---------- voice state tracking ----------
    def _cancel_delete(self, room: Room):
        task = self._delete_tasks.pop(room.channel_id, None)
        if task:
            task.cancel()

    def _schedule_delete(self, room: Room):
        if room.channel_id in self._delete_tasks:
            return
        task = asyncio.create_task(self._delay_delete(room))
        self._delete_tasks[room.channel_id] = task

    async def _delay_delete(self, room: Room):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        self._delete_tasks.pop(room.channel_id, None)
        channel = self.bot.get_channel(room.channel_id)
        if channel is None:
            return
        if room.permanent or len(channel.members) > 0:
            return
        await self.manager.delete_room(room)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.bot:
            return
        new_channel = after.channel
        if new_channel is not None:
            room = self.manager.get_room(new_channel.id)
            if room is not None:
                if before.channel is None or before.channel.id != new_channel.id:
                    channel = self.bot.get_channel(room.channel_id)
                    ow = channel.overwrites_for(member)
                    if ow.connect is not False:
                        await self.manager.add_member_role(member, room)
                if not room.permanent:
                    self._cancel_delete(room)
        if before.channel is not None:
            room = self.manager.get_room(before.channel.id)
            if room is not None:
                if after.channel is None or after.channel.id != before.channel.id:
                    await self.manager.remove_member_role(member, room)
                if not room.permanent:
                    self._schedule_delete(room)
