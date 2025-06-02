import json
import discord
import asyncio
import os
import time
from collections import defaultdict, deque
from discord.ext import commands
from discord import app_commands
import config
import random
import datetime
from config import (
    token as TOKEN,
    ALLOWED_CHANNELS,
    RESPOND_TO_PINGS,
    HISTORY_SIZE,
    DEBUG,
    SYSTEM_PROMPT,
    SYSTEM_SHORT,
    FREEWILL,
    JOIN_MSG
)
from memory import init_memory_files, save_memory, get_memory_detail, save_user_memory, get_user_memory_detail
from openai_client import generate_response

from pathlib import Path

SETTINGS_PATH = Path('serversettings.json')

def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text("{}", encoding="utf-8")
        return {}

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    if not isinstance(data, dict):
        data = {}

    return data

def save_settings(settings: dict):
    SETTINGS_PATH.write_text(json.dumps(settings, indent=4), encoding='utf-8')


# Rate limiting
RATE_LIMIT = 10
RATE_PERIOD = 60
user_requests = defaultdict(lambda: deque())

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Functions
tools = [
    {
        'name': 'save_memory',
        'description': 'Store a new memory.',
        'parameters': {
            'type': 'object',
            'properties': {
                'summary': {'type': 'string'},
                'full_memory': {'type': 'string'}
            },
            'required': ['summary', 'full_memory']
        }
    },
    {
        'name': 'get_memory_detail',
        'description': 'Retrieve a memory by its index.',
        'parameters': {
            'type': 'object',
            'properties': {'index': {'type': 'integer'}},
            'required': ['index']
        }
    },
    {
        'name': 'save_user_memory',
        'description': 'Store a new memory for a specific user.',
        'parameters': {
            'type': 'object',
            'properties': {
                'summary': {'type': 'string'},
                'full_memory': {'type': 'string'}
            },
            'required': ['summary', 'full_memory']
        }
    },
    {
        'name': 'get_user_memory_detail',
        'description': 'Retrieve a user memory by its index.',
        'parameters': {
            'type': 'object',
            'properties': {
                'index': {'type': 'integer'}
            },
            'required': ['index']
        }
    },
    {
        'name': 'cancel_response',
        'description': 'Cancel the current response.',
        'parameters': {'type': 'object', 'properties': {}}
    },
    {
        'name': 'set_status',
        'description': 'Change the bot presence status.',
        'parameters': {
            'type': 'object',
            'properties': {'status': {'type': 'string'}},
            'required': ['status']
        }
    },
    {
        'name': 'send_dm',
        'description': 'Sends a DM (direct message) rather than a normal message. Use send_followup to also send a normal message.',
        'parameters': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string'},
                'send_followup': {'type': 'boolean'}
            },
            'required': ['message', 'send_followup']
        }
    }
]

@bot.event
async def on_ready():
    init_memory_files()
    await bot.tree.sync()
    print(f"Ready as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    # Condition checking & free will
    if message.author.id == bot.user.id:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_allowed = message.channel.id in ALLOWED_CHANNELS
    is_pinged = RESPOND_TO_PINGS and bot.user in message.mentions
    if not (is_dm or is_allowed or is_pinged):
        settings = load_settings()
        sid = str(message.guild.id) if message.guild else None
        guild_settings = settings.get(sid, {})
        rate = guild_settings.get('freewill_rate', "mid")
        if rate == 0:
            return
        messages = [msg async for msg in message.channel.history(limit=2)]
        if len(messages) < 2:
            return
        msg = messages[1]
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - msg.created_at
        if delta.total_seconds() < 60 and msg.author.id == bot.user.id:
            if rate == "low":
                chance = 0.75
            if rate == "mid":
                chance = 0.9
            if rate == "high":
                chance = 1
        elif delta.total_seconds() > 36000:
            if rate == "low":
                chance = 0.25
            if rate == "mid":
                chance = 0.5
            if rate == "high":
                chance = 0.75
        elif delta.total_seconds() > 300:
            if rate == "low":
                chance = 0.05
            if rate == "mid":
                chance = 0.1
            if rate == "high":
                chance = 0.2
        else:
            if rate == "low":
                chance = 0.01
            if rate == "mid":
                chance = 0.05
            if rate == "high":
                chance = 0.1
        if random.random() <= chance:
            freewill = FREEWILL
        else:
            return
    else:
        freewill = None

    user_id = message.author.id
    now = time.time()
    dq = user_requests[user_id]
    while dq and now - dq[0] > RATE_PERIOD:
        dq.popleft()
    if len(dq) >= RATE_LIMIT:
        try:
            await message.channel.send(
                "You are going too fast. Let me take a breath pls."
            )
        except discord.Forbidden:
            pass
        return
    dq.append(now)

    # System prompt building
    history = []
    async for msg in message.channel.history(limit=HISTORY_SIZE+1, oldest_first=False):
        if msg.id == message.id:
            continue
        role = 'assistant' if msg.author.id == bot.user.id else 'user'
        content = msg.content if role == 'assistant' else f"{msg.author.display_name} ({msg.author.name}): {msg.content}"
        history.append({'role': role, 'content': content})
        if len(history) >= HISTORY_SIZE:
            break
    history.reverse()

    with open('summaries.json', 'r', encoding='utf-8') as f:
        summaries = json.load(f)
    summary_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries))

    channel_name = message.channel.name if not is_dm else 'DM'
    guild_name = message.guild.name if not is_dm else 'DM'
    system_content = (
        f"Server: {guild_name}\n"
        f"Channel: {channel_name}\n\n"
        f"{SYSTEM_PROMPT}\n"
        f"Current memories:\n{summary_list}"
    )

    user_content = []
    if message.content:
        user_content.append({'type': 'text', 'text': f"{message.author.display_name} ({message.author.name}): {message.content}"})
    for attach in message.attachments:
        if attach.content_type and attach.content_type.startswith('image/'):
            user_content.append({'type': 'image_url', 'image_url': {'url': attach.url}})

    if freewill:
        messages = [
        {'role': 'system', 'content': SYSTEM_SHORT},
        *history,
        {'role': 'user', 'content': user_content},
        {'role': 'system', 'content': freewill}
        ]
    else:
        messages = [
        {'role': 'system', 'content': system_content},
        *history,
        {'role': 'user', 'content': user_content}
        ]

    # Api request
    if DEBUG:
        print('--- REQUEST ---')
        print(json.dumps(messages, ensure_ascii=False, indent=2))

    if freewill:
        completion = await generate_response(
            messages,
            functions=tools,
            function_call='auto'
        )
    else:
        async with message.channel.typing():
            completion = await generate_response(
                messages,
                functions=tools,
                function_call='auto'
            )
    msg_obj = completion.choices[0].message

    # Functions
    if msg_obj.function_call is not None:
        name = msg_obj.function_call.name
        args = json.loads(msg_obj.function_call.arguments or '{}')
        if DEBUG:
            print(f"Function {name} called.")
        if name == 'save_memory':
            idx = save_memory(args['summary'], f"({message.author}) {args['full_memory']}")
            messages.append({'role': 'system', 'content': f'You just saved a new memory. Memory index: {idx}.'})
        elif name == 'get_memory_detail':
            detail = get_memory_detail(int(args['index']))
            messages.append({'role': 'system', 'content': f'You are recalling a stored memory. Memory content: {detail}.'})
        elif name == 'save_user_memory':
            idx = save_user_memory(message.author.id, args['summary'], args['full_memory'])
            messages.append({'role': 'system', 'content': f'User memory saved. Memory index for user {message.author.id}: {idx}.'})
        elif name == 'get_user_memory_detail':
            detail = get_user_memory_detail(message.author.id, int(args['index']))
            messages.append({'role': 'system', 'content': f'Recalling user memory for {message.author.id}: {detail}.'})
            print(f"index: {args['index']}, detail: {detail}")
        elif name == 'set_status':
            new_status = args['status']
            await bot.change_presence(activity=discord.CustomActivity(new_status))
            messages.append({'role': 'system', 'content': f'You changed your status to "{new_status}".'})
        elif name == 'cancel_response':
            return
        elif name == 'send_dm':
            dmmessage = args['message']
            user = message.author
            try:
                await user.send(dmmessage)
                messages.append({'role': 'system', 'content': f'DM sent to {user.name}.'})
            except discord.Forbidden:
                messages.append({'role': 'system', 'content': 'Something went wrong while trying to send a DM.'})
            if args['send_followup'] == False:
                return
        completion = await generate_response(
            messages,
            functions=None,
            function_call=None
        )
        msg_obj = completion.choices[0].message

    # Sending response
    if DEBUG:
        print('--- RESPONSE ---')
        print(msg_obj.content)
    if is_dm or is_allowed:
        await message.channel.send(msg_obj.content)
    else:
        await message.reply(msg_obj.content, mention_author=False)
    
# Server join message
@bot.event
async def on_guild_join(guild):
     if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        await guild.system_channel.send(JOIN_MSG)

# Commands, i want to move these to a seperate file
@bot.tree.command(name="activate", description="Make AI Nerd respond to all messages in this channel (or disable it)")
async def activate(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
        return

    chan_id = interaction.channel_id
    if chan_id in config.ALLOWED_CHANNELS:
        config.ALLOWED_CHANNELS.remove(chan_id)
        action = "no longer"
    else:
        config.ALLOWED_CHANNELS.append(chan_id)
        action = "now"
    config.save_allowed_channels()
    await interaction.response.send_message(
        f"AI Nerd will {action} respond to all messages in <#{chan_id}>.",
        ephemeral=False
    )

@bot.tree.command(name="freewill-rate", description="Control how often AI Nerd 2 responds without being pinged")
@app_commands.describe(rate="The frequency of random responses")
@app_commands.choices(rate=[
    app_commands.Choice(name="Low", value="low"),
    app_commands.Choice(name="Medium", value="mid"),
    app_commands.Choice(name="High", value="high"),
])
async def freewill_rate(interaction: discord.Interaction, rate: str):
    if not interaction.guild:
        return await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
    
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)

    settings = load_settings()
    sid = str(interaction.guild.id)
    guild_settings = settings.get(sid, {})
    guild_settings['freewill_rate'] = rate
    settings[sid] = guild_settings
    save_settings(settings)

    await interaction.response.send_message(f"Free will rate set to **{rate}**.")

# Runs the bot
if __name__ == '__main__':
    bot.run(TOKEN)