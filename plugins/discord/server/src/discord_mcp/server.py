import os
import sys
import base64
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List, Union
from functools import wraps
import discord
from discord.ext import commands
from mcp.server import Server
from mcp.types import Tool, TextContent, ImageContent
from mcp.server.stdio import stdio_server

def _configure_windows_stdout_encoding():
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

_configure_windows_stdout_encoding()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord-mcp-server")

# Discord bot setup
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is required")

# Initialize Discord bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize MCP server
app = Server("discord-server")

# Store Discord client reference
discord_client = None

@bot.event
async def on_ready():
    global discord_client
    discord_client = bot
    logger.info(f"Logged in as {bot.user.name}")

# Helper function to ensure Discord client is ready
def require_discord_client(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if not discord_client:
            raise RuntimeError("Discord client not ready")
        return await func(*args, **kwargs)
    return wrapper

# Tylko do odczytu: narzedzia zmieniajace cokolwiek w Discordzie sa wylaczone.
READ_ONLY_TOOLS = {
    "list_servers", "get_server_info", "get_channels",
    "list_members", "get_user_info", "read_messages",
    "get_attachment",
}

# Jedno wywolanie read_messages pobiera najwyzej tyle wiadomosci (discord.py sam stronicuje po 100).
MAX_MESSAGES = 1000
# Claude Code ucina duze odpowiedzi narzedzi, wiec wynik tniemy wczesniej i podajemy kursor do dalszej czesci.
MAX_OUTPUT_CHARS = 60000
# Limit rozmiaru pojedynczego obrazu przyjmowanego przez Claude.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_CALL = 5
MAX_TEXT_ATTACHMENT_CHARS = 50000

def _parse_history_point(value):
    """ID wiadomosci albo data ISO (np. 2026-01-01) -> punkt dla channel.history()."""
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip()
    if s.isdigit():
        return discord.Object(id=int(s))
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, size // 1024)} KB"

def _format_message(message: discord.Message) -> str:
    lines = [f"[{message.id}] {message.author} ({message.created_at.isoformat()}): {message.content}"]
    if message.reference and message.reference.message_id:
        lines.append(f"  odpowiedz na: {message.reference.message_id}")
    for i, a in enumerate(message.attachments, start=1):
        kind = a.content_type or "nieznany typ"
        dims = f", {a.width}x{a.height}" if a.width and a.height else ""
        lines.append(f"  zalacznik {i}: {a.filename} ({kind}, {_format_size(a.size)}{dims})")
    for e in message.embeds:
        parts = [p for p in (e.title, e.url) if p]
        image = (e.image and e.image.url) or (e.thumbnail and e.thumbnail.url)
        if image:
            parts.append(f"obraz: {image}")
        if parts:
            lines.append("  osadzenie: " + " | ".join(parts))
    for s in message.stickers:
        lines.append(f"  naklejka: {s.name}")
    if message.reactions:
        reactions = ", ".join(
            f"{getattr(r.emoji, 'name', None) or r.emoji}({r.count})" for r in message.reactions
        )
        lines.append(f"  reakcje: {reactions}")
    return "\n".join(lines)

@app.list_tools()
async def list_tools() -> List[Tool]:
    """List available Discord tools."""
    return [t for t in _all_tools() if t.name in READ_ONLY_TOOLS]

def _all_tools() -> List[Tool]:
    return [
        # Server Information Tools
        Tool(
            name="get_server_info",
            description="Get information about a Discord server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "string",
                        "description": "Discord server (guild) ID"
                    }
                },
                "required": ["server_id"]
            }
        ),
        Tool(
            name="get_channels",
            description="Get a list of all channels in a Discord server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "string",
                        "description": "Discord server (guild) ID"
                    }
                },
                "required": ["server_id"]
            }
        ),
        Tool(
            name="list_members",
            description="Get a list of members in a server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "string",
                        "description": "Discord server (guild) ID"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of members to fetch",
                        "minimum": 1,
                        "maximum": 1000
                    }
                },
                "required": ["server_id"]
            }
        ),

        # Role Management Tools
        Tool(
            name="add_role",
            description="Add a role to a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "string",
                        "description": "Discord server ID"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User to add role to"
                    },
                    "role_id": {
                        "type": "string",
                        "description": "Role ID to add"
                    }
                },
                "required": ["server_id", "user_id", "role_id"]
            }
        ),
        Tool(
            name="remove_role",
            description="Remove a role from a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "string",
                        "description": "Discord server ID"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User to remove role from"
                    },
                    "role_id": {
                        "type": "string",
                        "description": "Role ID to remove"
                    }
                },
                "required": ["server_id", "user_id", "role_id"]
            }
        ),

        # Channel Management Tools
        Tool(
            name="create_text_channel",
            description="Create a new text channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "string",
                        "description": "Discord server ID"
                    },
                    "name": {
                        "type": "string",
                        "description": "Channel name"
                    },
                    "category_id": {
                        "type": "string",
                        "description": "Optional category ID to place channel in"
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional channel topic"
                    }
                },
                "required": ["server_id", "name"]
            }
        ),
        Tool(
            name="delete_channel",
            description="Delete a channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "ID of channel to delete"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for deletion"
                    }
                },
                "required": ["channel_id"]
            }
        ),

        # Message Reaction Tools
        Tool(
            name="add_reaction",
            description="Add a reaction to a message",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel containing the message"
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message to react to"
                    },
                    "emoji": {
                        "type": "string",
                        "description": "Emoji to react with (Unicode or custom emoji ID)"
                    }
                },
                "required": ["channel_id", "message_id", "emoji"]
            }
        ),
        Tool(
            name="add_multiple_reactions",
            description="Add multiple reactions to a message",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel containing the message"
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message to react to"
                    },
                    "emojis": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Emoji to react with (Unicode or custom emoji ID)"
                        },
                        "description": "List of emojis to add as reactions"
                    }
                },
                "required": ["channel_id", "message_id", "emojis"]
            }
        ),
        Tool(
            name="remove_reaction",
            description="Remove a reaction from a message",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel containing the message"
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message to remove reaction from"
                    },
                    "emoji": {
                        "type": "string",
                        "description": "Emoji to remove (Unicode or custom emoji ID)"
                    }
                },
                "required": ["channel_id", "message_id", "emoji"]
            }
        ),
        Tool(
            name="send_message",
            description="Send a message to a specific channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Discord channel ID"
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content"
                    }
                },
                "required": ["channel_id", "content"]
            }
        ),
        Tool(
            name="read_messages",
            description=(
                "Read messages from a channel, including attachments (images, files), embeds and replies. "
                "Each message starts with its ID in brackets. Use 'after'/'before' (message ID or ISO date) "
                "for a time range; if the output is cut, it ends with the exact 'before'/'after' value "
                "for the next call. View an attached image with get_attachment."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Discord channel ID"
                    },
                    "limit": {
                        "type": "number",
                        "description": f"Number of messages to fetch (default 50, max {MAX_MESSAGES})",
                        "minimum": 1,
                        "maximum": MAX_MESSAGES
                    },
                    "before": {
                        "type": "string",
                        "description": "Only messages older than this message ID or ISO date (e.g. 2026-06-30)"
                    },
                    "after": {
                        "type": "string",
                        "description": "Only messages newer than this message ID or ISO date (e.g. 2026-01-01)"
                    },
                    "oldest_first": {
                        "type": "boolean",
                        "description": "Chronological order. Default: newest first, or oldest first when 'after' is set"
                    }
                },
                "required": ["channel_id"]
            }
        ),
        Tool(
            name="get_attachment",
            description=(
                "Fetch attachments of one message so they can be viewed: images are returned as images, "
                "text files (txt, csv, json, ...) as text, other files as a description only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Discord channel ID"
                    },
                    "message_id": {
                        "type": "string",
                        "description": "ID of the message with attachments (from read_messages)"
                    },
                    "attachment": {
                        "type": "number",
                        "description": f"Attachment number from read_messages (1, 2, ...). Omit to get all (max {MAX_IMAGES_PER_CALL} images)",
                        "minimum": 1
                    }
                },
                "required": ["channel_id", "message_id"]
            }
        ),
        Tool(
            name="get_user_info",
            description="Get information about a Discord user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord user ID"
                    }
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="moderate_message",
            description="Delete a message and optionally timeout the user",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel ID containing the message"
                    },
                    "message_id": {
                        "type": "string",
                        "description": "ID of message to moderate"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for moderation"
                    },
                    "timeout_minutes": {
                        "type": "number",
                        "description": "Optional timeout duration in minutes",
                        "minimum": 0,
                        "maximum": 40320  # Max 4 weeks
                    }
                },
                "required": ["channel_id", "message_id", "reason"]
            }
        ),
        Tool(
            name="list_servers",
            description="Get a list of all Discord servers the bot has access to with their details such as name, id, member count, and creation date.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]

@app.call_tool()
@require_discord_client
async def call_tool(name: str, arguments: Any) -> List[Union[TextContent, ImageContent]]:
    """Handle Discord tool calls."""
    if name not in READ_ONLY_TOOLS:
        raise ValueError(f"Tool disabled (read-only server): {name}")

    if name == "send_message":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        message = await channel.send(arguments["content"])
        return [TextContent(
            type="text",
            text=f"Message sent successfully. Message ID: {message.id}"
        )]

    elif name == "read_messages":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        limit = max(1, min(int(arguments.get("limit", 50)), MAX_MESSAGES))
        try:
            before = _parse_history_point(arguments.get("before"))
            after = _parse_history_point(arguments.get("after"))
        except ValueError as e:
            return [TextContent(type="text", text=f"Bledny format 'before'/'after' (podaj ID wiadomosci albo date ISO): {e}")]
        history_args = {"limit": limit, "before": before, "after": after}
        if arguments.get("oldest_first") is not None:
            history_args["oldest_first"] = bool(arguments["oldest_first"])

        blocks = []
        used = 0
        last = None
        cut = False
        async for message in channel.history(**history_args):
            block = _format_message(message)
            if blocks and used + len(block) > MAX_OUTPUT_CHARS:
                cut = True
                break
            blocks.append(block)
            used += len(block) + 1
            last = message

        if not blocks:
            return [TextContent(type="text", text="Brak wiadomosci w podanym zakresie.")]

        header = f"Retrieved {len(blocks)} messages ({blocks[0].split(' ', 1)[0]} .. {blocks[-1].split(' ', 1)[0]}):"
        text = header + "\n\n" + "\n".join(blocks)
        if cut or len(blocks) == limit:
            # Kolejnosc chronologiczna -> dalej idziemy w przod (after), odwrotna -> w tyl (before).
            chronological = history_args.get("oldest_first", after is not None)
            cursor = "after" if chronological else "before"
            reason = "Wynik uciety ze wzgledu na rozmiar" if cut else "Osiagnieto limit"
            text += f"\n\n{reason}. Dalsze wiadomosci: wywolaj ponownie z {cursor}=\"{last.id}\"."
        return [TextContent(type="text", text=text)]

    elif name == "get_attachment":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        # Swieze pobranie wiadomosci daje aktualne (podpisane, wygasajace) adresy plikow.
        message = await channel.fetch_message(int(arguments["message_id"]))
        attachments = list(enumerate(message.attachments, start=1))
        if not attachments:
            return [TextContent(type="text", text="Ta wiadomosc nie ma zalacznikow.")]
        if arguments.get("attachment") is not None:
            index = int(arguments["attachment"])
            attachments = [(i, a) for i, a in attachments if i == index]
            if not attachments:
                return [TextContent(type="text", text=f"Brak zalacznika nr {index} (wiadomosc ma {len(message.attachments)}).")]

        result: List[Union[TextContent, ImageContent]] = []
        images = 0
        for i, a in attachments:
            kind = (a.content_type or "").split(";")[0].strip().lower()
            label = f"Zalacznik {i}: {a.filename} ({kind or 'nieznany typ'}, {_format_size(a.size)})"
            if kind.startswith("image/"):
                if a.size > MAX_IMAGE_BYTES:
                    result.append(TextContent(type="text", text=f"{label} - za duzy do podgladu (limit {_format_size(MAX_IMAGE_BYTES)})."))
                    continue
                if images >= MAX_IMAGES_PER_CALL:
                    result.append(TextContent(type="text", text=f"{label} - pominiety, limit {MAX_IMAGES_PER_CALL} obrazow na wywolanie; pobierz go z attachment={i}."))
                    continue
                data = await a.read()
                result.append(TextContent(type="text", text=label))
                result.append(ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mimeType=kind))
                images += 1
            elif kind.startswith("text/") or kind in ("application/json", "application/xml", "application/csv"):
                data = await a.read()
                content = data.decode("utf-8", errors="replace")
                if len(content) > MAX_TEXT_ATTACHMENT_CHARS:
                    content = content[:MAX_TEXT_ATTACHMENT_CHARS] + "\n[... uciete]"
                result.append(TextContent(type="text", text=f"{label}:\n{content}"))
            else:
                result.append(TextContent(type="text", text=f"{label} - tego typu pliku nie da sie podejrzec."))
        return result

    elif name == "get_user_info":
        user = await discord_client.fetch_user(int(arguments["user_id"]))
        user_info = {
            "id": str(user.id),
            "name": user.name,
            "discriminator": user.discriminator,
            "bot": user.bot,
            "created_at": user.created_at.isoformat()
        }
        return [TextContent(
            type="text",
            text=f"User information:\n" + 
                 f"Name: {user_info['name']}#{user_info['discriminator']}\n" +
                 f"ID: {user_info['id']}\n" +
                 f"Bot: {user_info['bot']}\n" +
                 f"Created: {user_info['created_at']}"
        )]

    elif name == "moderate_message":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        message = await channel.fetch_message(int(arguments["message_id"]))
        
        # Delete the message
        await message.delete(reason=arguments["reason"])
        
        # Handle timeout if specified
        if "timeout_minutes" in arguments and arguments["timeout_minutes"] > 0:
            if isinstance(message.author, discord.Member):
                duration = discord.utils.utcnow() + datetime.timedelta(
                    minutes=arguments["timeout_minutes"]
                )
                await message.author.timeout(
                    duration,
                    reason=arguments["reason"]
                )
                return [TextContent(
                    type="text",
                    text=f"Message deleted and user timed out for {arguments['timeout_minutes']} minutes."
                )]
        
        return [TextContent(
            type="text",
            text="Message deleted successfully."
        )]

    # Server Information Tools
    elif name == "get_server_info":
        guild = await discord_client.fetch_guild(int(arguments["server_id"]))
        info = {
            "name": guild.name,
            "id": str(guild.id),
            "owner_id": str(guild.owner_id),
            "member_count": guild.member_count,
            "created_at": guild.created_at.isoformat(),
            "description": guild.description,
            "premium_tier": guild.premium_tier,
            "explicit_content_filter": str(guild.explicit_content_filter)
        }
        return [TextContent(
            type="text",
            text=f"Server Information:\n" + "\n".join(f"{k}: {v}" for k, v in info.items())
        )]

    elif name == "get_channels":
        try:
            guild = discord_client.get_guild(int(arguments["server_id"]))
            if guild:
                channel_list = []
                for channel in guild.channels:
                    channel_list.append(f"#{channel.name} (ID: {channel.id}) - {channel.type}")
                
                return [TextContent(
                    type="text", 
                    text=f"Channels in {guild.name}:\n" + "\n".join(channel_list)
                )]
            else:
                return [TextContent(type="text", text="Guild not found")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "list_members":
        guild = await discord_client.fetch_guild(int(arguments["server_id"]))
        limit = min(int(arguments.get("limit", 100)), 1000)
        
        members = []
        async for member in guild.fetch_members(limit=limit):
            members.append({
                "id": str(member.id),
                "name": member.name,
                "nick": member.nick,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "roles": [str(role.id) for role in member.roles[1:]]  # Skip @everyone
            })
        
        return [TextContent(
            type="text",
            text=f"Server Members ({len(members)}):\n" + 
                 "\n".join(f"{m['name']} (ID: {m['id']}, Roles: {', '.join(m['roles'])})" for m in members)
        )]

    # Role Management Tools
    elif name == "add_role":
        guild = await discord_client.fetch_guild(int(arguments["server_id"]))
        member = await guild.fetch_member(int(arguments["user_id"]))
        role = guild.get_role(int(arguments["role_id"]))
        
        await member.add_roles(role, reason="Role added via MCP")
        return [TextContent(
            type="text",
            text=f"Added role {role.name} to user {member.name}"
        )]

    elif name == "remove_role":
        guild = await discord_client.fetch_guild(int(arguments["server_id"]))
        member = await guild.fetch_member(int(arguments["user_id"]))
        role = guild.get_role(int(arguments["role_id"]))
        
        await member.remove_roles(role, reason="Role removed via MCP")
        return [TextContent(
            type="text",
            text=f"Removed role {role.name} from user {member.name}"
        )]

    # Channel Management Tools
    elif name == "create_text_channel":
        guild = await discord_client.fetch_guild(int(arguments["server_id"]))
        category = None
        if "category_id" in arguments:
            category = guild.get_channel(int(arguments["category_id"]))
        
        channel = await guild.create_text_channel(
            name=arguments["name"],
            category=category,
            topic=arguments.get("topic"),
            reason="Channel created via MCP"
        )
        
        return [TextContent(
            type="text",
            text=f"Created text channel #{channel.name} (ID: {channel.id})"
        )]

    elif name == "delete_channel":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        await channel.delete(reason=arguments.get("reason", "Channel deleted via MCP"))
        return [TextContent(
            type="text",
            text=f"Deleted channel successfully"
        )]

    # Message Reaction Tools
    elif name == "add_reaction":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        message = await channel.fetch_message(int(arguments["message_id"]))
        await message.add_reaction(arguments["emoji"])
        return [TextContent(
            type="text",
            text=f"Added reaction {arguments['emoji']} to message"
        )]

    elif name == "add_multiple_reactions":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        message = await channel.fetch_message(int(arguments["message_id"]))
        for emoji in arguments["emojis"]:
            await message.add_reaction(emoji)
        return [TextContent(
            type="text",
            text=f"Added reactions: {', '.join(arguments['emojis'])} to message"
        )]

    elif name == "remove_reaction":
        channel = await discord_client.fetch_channel(int(arguments["channel_id"]))
        message = await channel.fetch_message(int(arguments["message_id"]))
        await message.remove_reaction(arguments["emoji"], discord_client.user)
        return [TextContent(
            type="text",
            text=f"Removed reaction {arguments['emoji']} from message"
        )]

    elif name == "list_servers":
        servers = []
        for guild in discord_client.guilds:
            servers.append({
                "id": str(guild.id),
                "name": guild.name,
                "member_count": guild.member_count,
                "created_at": guild.created_at.isoformat()
            })
        
        return [TextContent(
            type="text",
            text=f"Available Servers ({len(servers)}):\n" + 
                 "\n".join(f"{s['name']} (ID: {s['id']}, Members: {s['member_count']})" for s in servers)
        )]

    raise ValueError(f"Unknown tool: {name}")

async def main():
    # Start Discord bot in the background
    asyncio.create_task(bot.start(DISCORD_TOKEN))
    
    # Run MCP server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
