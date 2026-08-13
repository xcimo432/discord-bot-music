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


class PanelView(discord.ui.View):
    def __init__(self, cog, owner_id: int):
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

    async def _reply_success(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(embed=discord.Embed(description=text, color=GREEN), ephemeral=True)

    async def _reply_error(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(embed=discord.Embed(description=text, color=RED), ephemeral=True)

    async def send_panel(self, member: discord.Member, room: Room):
        channel = self.bot.get_channel(room.channel_id)
        name = channel.name if channel else "Комната"
        em = discord.Embed(
            title="🎛 Панель управления комнатой",
            description=f"Управляйте комнатой **«{name}»** кнопками ниже.",
            color=GREY,
        )
        view = PanelView(self, room.owner_id)
        try:
            dm = await member.create_dm()
            await dm.send(embed=em, view=view)
        except discord.HTTPException:
            pass

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
            f"✅ Создан голосовой канал «**{channel.name}**». Вы — владелец.",
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

    @app_commands.command(name="delete", description="Удалить комнату")
    async def delete(self, interaction: discord.Interaction):
        room = self.manager.get_owner_room(interaction.user.id)
        if room is None:
            await self._reply_error(interaction, "❌ У вас нет приватной комнаты.")
            return
        await self._delete_room(interaction, room)

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

    async def _delete_room(self, interaction, room):
        await self.manager.delete_room(room)
        await self._reply_success(interaction, "🗑 Комната удалена.")

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
