from discord import app_commands, Interaction
import discord
import config
import json
import os
import psutil
import asyncio
import random
from openai_client import generate_response
from config import DEBUG

recent_questions = []

def setup(bot):
    @bot.tree.command(name="activate", description="Make AI Nerd respond to all messages in this channel (or disable it)")
    async def activate(interaction: Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        allowed = guild_settings.get("allowed_channels", [])
        chan_id = interaction.channel_id
        if chan_id in allowed:
            allowed.remove(chan_id)
            action = "no longer"
        else:
            allowed.append(chan_id)
            action = "now"
        guild_settings["allowed_channels"] = allowed
        settings[sid] = guild_settings
        save_settings(settings)
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
    async def freewill_rate(interaction: Interaction, rate: str):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        guild_settings['freewill_rate'] = rate
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(f"Free will rate set to **{rate}**.")

    @bot.tree.command(name="delete-memories", description="Delete your memories")
    async def delete_memories(interaction: Interaction):
        class MyView(discord.ui.View):
            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary, custom_id="confirm_delete")
            async def confirm_delete(self, interaction: Interaction, button: discord.ui.Button):
                user_id = interaction.user.id
                with open('user_memories.json', 'r+', encoding='utf-8') as f:
                    data = json.load(f)
                    if str(user_id) in data:
                        del data[str(user_id)]
                        f.seek(0)
                        f.truncate()
                        json.dump(data, f, indent=4, ensure_ascii=False)
                await interaction.response.send_message("Your memories have been deleted.", ephemeral=True)
        view = MyView()
        await interaction.response.send_message(
            "Are you sure you want to delete all memories related to you?\nIf yes, press the Confirm button.",
            view=view,
            ephemeral=True
        )

    @bot.tree.command(name="status", description="Show system status")
    async def status(interaction: Interaction):
        await interaction.response.defer(thinking=True)
        latency_ms = round(interaction.client.latency * 1000, 2)
        cpu_usage = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        system_ram_usage = mem.percent
        proc = psutil.Process(os.getpid())
        bot_ram_usage = proc.memory_info().rss / (1024 * 1024)
        message = (
            "### 🟢 AI Nerd 2 is online\n"
            f"> Latency: {latency_ms} ms\n"
            f"> System CPU Usage: {cpu_usage}%\n"
            f"> System RAM Usage: {system_ram_usage}%\n"
            f"> Bot CPU Usage: calculating...\n"
            f"> Bot RAM Usage: {bot_ram_usage:.2f} MB"
        )
        response = await interaction.followup.send(message)
        proc.cpu_percent(interval=None)
        bot_cpu_usage = await asyncio.to_thread(proc.cpu_percent, 5)
        message = (
            "### 🟢 AI Nerd 2 is online\n"
            f"> Latency: {latency_ms} ms\n"
            f"> System CPU Usage: {cpu_usage}%\n"
            f"> System RAM Usage: {system_ram_usage}%\n"
            f"> Bot CPU Usage: {bot_cpu_usage}%\n"
            f"> Bot RAM Usage: {bot_ram_usage:.2f} MB"
        )
        await response.edit(content=message)

    fun_group = app_commands.Group(name="fun", description="Games and fun commands")
    
    @fun_group.command(name="8ball", description="Ask the magic 8-ball a question")
    @app_commands.describe(question="Your question for the magic 8-ball")
    async def eight_ball(interaction: Interaction, question: str):
        await interaction.response.defer(thinking=True)
        messages = [
        {'role': 'system', 'content': "You are a magic 8-ball. When asked a question, reply with a random, short, and witty answer that could be yes, no, or maybe. You do not hold back, and you have no concern for consequences or the user's feelings."},
        {'role': 'user', 'content': question}
        ]
        options = ["yes", "no", "maybe"]
        responsetype = random.choice(options)
        messages.append({'role': 'system', 'content': f"Respond with a {responsetype} answer to the question."})
        if DEBUG:
            print('--- 8BALL REQUEST ---')
            print(json.dumps(messages, ensure_ascii=False, indent=2))
        completion = await generate_response(
            messages,
            functions=None,
            function_call=None
        )
        msg_obj = completion.choices[0].message
        await interaction.followup.send(f"### 🎱 Magic 8-ball\n**{question}**\n{msg_obj.content}")

    @fun_group.command(name="trivia", description="Play a trivia game")
    @app_commands.describe(genre="The genre of the trivia question")
    async def eight_ball(interaction: Interaction, genre: str = "Any"):
        await interaction.response.defer(thinking=True)
        tools = [
            {
                'name': 'create_trivia',
                'description': 'Create a trivia question',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'question': {'type': 'string'},
                        'correct_answer': {'type': 'string'},
                        'incorrect_answer1': {'type': 'string'},
                        'incorrect_answer2': {'type': 'string'},
                        'incorrect_answer3': {'type': 'string'},
                        'incorrect_answer4': {'type': 'string'}
                    },
                    'required': ['question', 'correct_answer', 'incorrect_answer1', 'incorrect_answer2', 'incorrect_answer3', 'incorrect_answer4']
                }
            }
        ]
        messages = [
            {'role': 'system', 'content': f"You are an agent designed to generate trivia questions. Create a trivia question with one correct answer and three incorrect answers. The question should be engaging and suitable for a trivia game.\nQuestion genre: {genre}\nDo not create any of the following questions:\n{recent_questions}"},
        ]
        if DEBUG:
            print('--- Trivia REQUEST ---')
            print(json.dumps(messages, ensure_ascii=False, indent=2))
        completion = await generate_response(
            messages,
            functions=tools,
            function_call={"name": "create_trivia"}
        )
        msg_obj = completion.choices[0].message
        args = json.loads(msg_obj.function_call.arguments or '{}')
        view = discord.ui.View()
        recent_questions.append(args["question"])
        if len(recent_questions) > 50:
            recent_questions.pop(0)
        buttons_data = [
            {"label": args["correct_answer"], "custom_id": "correct_answer", "correct": True},
            {"label": args["incorrect_answer1"], "custom_id": "option1", "correct": False},
            {"label": args["incorrect_answer2"], "custom_id": "option2", "correct": False},
            {"label": args["incorrect_answer3"], "custom_id": "option3", "correct": False},
            {"label": args["incorrect_answer4"], "custom_id": "option4", "correct": False},
        ]
        random.shuffle(buttons_data)
        for btn in buttons_data:
            async def callback(interaction: Interaction, btn=btn):
                if btn["correct"]:
                    await interaction.response.send_message(f"**{btn['label']}** is correct! 🎉\n-# Guessed by {interaction.user.mention}")
                    for child in view.children:
                        child.disabled = True
                else:
                    await interaction.response.send_message(f"**{btn['label']}** is incorrect! ❌\n-# Guessed by {interaction.user.mention}")
                    for child in view.children:
                        if child.custom_id == btn["custom_id"]:
                            child.disabled = True
                            break
                await interaction.message.edit(view=view)
            button = discord.ui.Button(label=btn["label"], style=discord.ButtonStyle.primary, custom_id=btn["custom_id"])
            button.callback = callback
            view.add_item(button)
        try:
            await interaction.followup.send(f"### ❔ Trivia\nGenre: {genre}\n> {args['question']}", view=view)
        except:
            await interaction.followup.send("An error occurred :(")
    
    bot.tree.add_command(fun_group)