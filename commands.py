from discord import app_commands, Interaction
import discord
import json
import os
import psutil
import asyncio
import random
import time
import datetime
import requests
import sys
import numpy as np
from ollama import ps
from openai_client import generate_response, embed_text
from config import DEBUG, OWNER_ID, COMMANDS_MODEL, IMAGE_MODEL
from nerdscore import get_nerdscore, increase_nerdscore, load_nerdscore
import storage
from memory import delete_user_memories
import abuse_detection
import metrics

def load_recent_questions():
    return storage.load_recent_questions() or {}

def save_recent_questions(data):
    storage.save_recent_questions(data or {})

def load_daily_quiz_records():
    return storage.load_daily_quiz_records() or {}

def save_daily_quiz_records(data):
    storage.save_daily_quiz_records(data or {})

def cosine(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def setup(bot):
    config_group = app_commands.Group(name="config", description="Configuration")

    @config_group.command(name="activate", description="Make AI Nerd respond to all messages in this channel (or disable it)")
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
            permissions = interaction.channel.permissions_for(interaction.guild.me)
            if not permissions.send_messages:
                await interaction.response.send_message("I do not have permission to send messages in this channel.", ephemeral=True)
                return
            allowed.append(chan_id)
            action = "now"
        guild_settings["allowed_channels"] = allowed
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"AI Nerd will {action} respond to all messages in <#{chan_id}>.",
            ephemeral=False
        )

    @config_group.command(name="natural-replies", description="Control how often AI Nerd 2 responds without being pinged")
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
        await interaction.response.send_message(f"Natural replies rate set to **{rate}**.")

    @config_group.command(name="welcome", description="Toggle welcome messages in this channel")
    async def freewill_rate(interaction: Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        permissions = interaction.channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages:
            await interaction.response.send_message("I do not have permission to send messages in this channel.", ephemeral=True)
            return
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        allowed = guild_settings.get("welcome_msg", None)
        chan_id = interaction.channel_id
        if allowed == chan_id:
            guild_settings["welcome_msg"] = None
            action = "no longer"
        else:
            guild_settings["welcome_msg"] = chan_id
            action = "now"
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"AI Nerd 2 will {action} welcome new members in <#{chan_id}>.",
            ephemeral=False
        )

    @config_group.command(name="chatrevive-set", description="Make AI Nerd 2 send a chat revive message when the channel is inactive")
    @app_commands.describe(timeout="Time since last message in minutes before revive message is sent", role="Role to mention for chat revive")
    async def chatrevive(interaction: Interaction, timeout: app_commands.Range[int, 30, None], role: discord.Role):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        permissions = interaction.channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages:
            await interaction.response.send_message("I do not have permission to send messages in this channel.", ephemeral=True)
            return
        
        can_mention = False
        bot_member = interaction.guild.me
        if (permissions.mention_everyone and bot_member.top_role > role) or role.mentionable:
            can_mention = True
        if not can_mention:
            await interaction.response.send_message(
                f"I do not have permission to mention the role {role.mention} in this channel.",
                ephemeral=True
            )
            return

        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        chatrevive = guild_settings.get("chatrevive", {})
        chan_id = interaction.channel_id
        if role is None:
            await interaction.response.send_message("You must specify a role to mention for chat revive.", ephemeral=True)
            return
        guild_settings["chatrevive"] = {
            "channel_id": chan_id,
            "timeout": timeout,
            "role_id": role.id
        }
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"Chat revive enabled for <#{chan_id}>. Timeout: {timeout} minutes. Role to mention: {role.mention}",
            ephemeral=False
        )

    @config_group.command(name="chatrevive-disable", description="Disable chat revive messages in this server.")
    async def chatrevive(interaction: Interaction):
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
        chatrevive = guild_settings.get("chatrevive", {})
        chan_id = interaction.channel_id
        setting_chan_id = chatrevive.get("channel_id")
        if chatrevive.get("channel_id"):
            guild_settings["chatrevive"] = {}
            settings[sid] = guild_settings
            save_settings(settings)
            await interaction.response.send_message(f"Chat revive is now disabled for <#{setting_chan_id}>.", ephemeral=False)
        else:
            await interaction.response.send_message(f"Chat revive is already disabled in this server.", ephemeral=False)

    bot.tree.add_command(config_group)

    @bot.tree.command(name="delete-memories", description="Delete your memories")
    async def delete_memories(interaction: Interaction):
        class MyView(discord.ui.View):
            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary, custom_id="confirm_delete")
            async def confirm_delete(self, interaction: Interaction, button: discord.ui.Button):
                user_id = interaction.user.id
                delete_user_memories(user_id)
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
        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)
        latency_ms = round(interaction.client.latency * 1000, 2)
        bot_ram_usage = proc.memory_info().rss / (1024 * 1024)
        try:
            metrics_data = storage.load_user_metrics() or {}
            user_count = len(metrics_data)
        except Exception:
            user_count = 0
        bot_cpu_usage = proc.cpu_percent(interval=0)
        message = (
            "### 🟢 AI Nerd 2 is online\n"
            f"> Latency: {latency_ms} ms\n"
            f"> CPU Usage: {bot_cpu_usage}%\n"
            f"> RAM Usage: {bot_ram_usage:.2f} MB\n"
            f"> Server count: {len(bot.guilds)}\n"
            f"> User count: {user_count}\n"
        )
        await interaction.followup.send(message)

    fun_group = app_commands.Group(name="fun", description="Games and fun commands")
    
    @fun_group.command(name="8ball", description="Ask the magic 8-ball a question")
    @app_commands.describe(question="Your question for the magic 8-ball")
    async def eight_ball(interaction: Interaction, question: str):
        await interaction.response.defer(thinking=True)

        input_list = [
            {"role": "system", "content": "You are a magic 8-ball. When asked a question, reply with a random, short, and witty answer that could be yes, no, or maybe. You do not hold back, and you have no concern for consequences or the user's feelings."},
            {"role": "user", "content": question}
        ]

        options = ["yes", "no", "maybe"]
        responsetype = random.choice(options)
        input_list.append({"role": "system", "content": f"Respond with a {responsetype} answer to the question."})

        if DEBUG:
            print('--- 8BALL REQUEST ---')
            print(json.dumps(input_list, ensure_ascii=False, indent=2))

        completion = await generate_response(
            input_list,
            tools=None,
            tool_choice=None,
            user = f"8ball_{interaction.user.name}:{interaction.user.id}"
        )

        msg_text = completion.output_text

        if DEBUG:
            print('--- RESPONSE ---')
            print(msg_text)

        await interaction.followup.send(f"### 🎱 Magic 8-ball\n**{question}**\n{msg_text}")

    @fun_group.command(name="trivia", description="Play a trivia game")
    @app_commands.describe(genre="The genre of the trivia question")
    @app_commands.describe(difficulty="The difficulty of the trivia question")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy", value="Easy"),
        app_commands.Choice(name="Medium", value="Medium"),
        app_commands.Choice(name="Hard", value="Hard"),
    ])
    async def trivia(interaction: Interaction, genre: str = "Any", difficulty: str = 'Any'):
        await interaction.response.defer(thinking=True)
        properties = {
            'question': {'type': 'string'},
            'correct_answer': {'type': 'string'},
            'incorrect_answer1': {'type': 'string'},
            'incorrect_answer2': {'type': 'string'},
            'incorrect_answer3': {'type': 'string'},
            'incorrect_answer4': {'type': 'string'},
        }
        property_names = ['question', 'correct_answer', 'incorrect_answer1', 'incorrect_answer2', 'incorrect_answer3', 'incorrect_answer4']
        if genre == "Any":
            properties['genre'] = {'type': 'string'}
            property_names.append('genre')
        if difficulty == 'Any':
            properties['difficulty'] = {'type': 'string', 'enum': ['Easy', 'Medium', 'Hard']}
            property_names.append('difficulty')
        tools = [
            {
                'name': 'create_trivia',
                'description': 'Create a trivia question',
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                    'required': property_names
                }
            }
        ]
        
        messages = [{'role': 'developer', 'content': f"You are an agent designed to generate trivia questions. Create a trivia question with one correct answer and four incorrect answers. The question should be engaging and suitable for a trivia game.\nQuestion genre: {genre}\nQuestion difficulty: {difficulty}"}]
        user_id = str(interaction.user.id)
        questions_data = load_recent_questions()

        MAX_RETRIES = 3
        for _ in range(MAX_RETRIES):
            if DEBUG:
                print('--- TRIVIA REQUEST ---')
                print(json.dumps(messages, ensure_ascii=False, indent=2))
            completion = await generate_response(
                messages,
                tools=tools,
                tool_choice={"type": "function", "name": "create_trivia"},
                model=COMMANDS_MODEL,
                user = f"trivia_{interaction.user.name}:{interaction.user.id}"
            )
            args = {}
            for item in completion.output:
                if item.type == "function_call":
                    args = json.loads(item.arguments or "{}")
            if DEBUG:
                print('--- RESPONSE ---')
                print(args)

            if 'genre' in args:
                genre = args['genre']
            if 'difficulty' in args:
                difficulty = args['difficulty']

            if user_id not in questions_data:
                questions_data[user_id] = {}
            if genre not in questions_data[user_id]:
                questions_data[user_id][genre] = []

            user_recent = questions_data[user_id][genre]

            new_emb = embed_text(args["question"])
            similar = False
            for prev in user_recent:
                if "emb" not in prev:
                    continue
                score = cosine(new_emb, np.array(prev["emb"], dtype=np.float32))
                if DEBUG:
                    print(f"Cosine similarity with previous question '{prev['q']}': {score}")
                if score > 0.85:
                    similar = True
                    break

            if not similar:
                break
        else:
            await interaction.followup.send("An error occurred while creating the trivia question. Please try again.")
            return

        user_recent.append({"q": args["question"], "emb": new_emb})
        if len(user_recent) > 50:
            user_recent.pop(0)
        questions_data[user_id][genre] = user_recent
        save_recent_questions(questions_data)
        
        question_time = time.monotonic()
        view = discord.ui.View()
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
                    answer_time = time.monotonic()
                    if difficulty == 'Easy':
                        multiplier = 0.5
                    if difficulty == 'Medium':
                        multiplier = 1.0
                    if difficulty == 'Hard':
                        multiplier = 1.5
                    points = max(0, int(round((30 - (answer_time - question_time)) * multiplier, 0)))
                    if points > 0:
                        await interaction.response.send_message(f"**{btn['label']}** is correct! 🎉\n-# {interaction.user.mention} guessed it after {max(0, int(round((answer_time - question_time), 0)))} seconds and earned {points} nerdscore")
                        increase_nerdscore(interaction.user.id, points)
                    else:
                        await interaction.response.send_message(f"**{btn['label']}** is correct! 🎉\n-# {interaction.user.mention} guessed it after {max(0, int(round((answer_time - question_time), 0)))} seconds")
                    for child in view.children:
                        child.disabled = True
                        if child.custom_id == btn["custom_id"]:
                            child.style = discord.ButtonStyle.success
                        elif child.style == discord.ButtonStyle.primary:
                            child.style = discord.ButtonStyle.danger
                else:
                    await interaction.response.send_message(f"**{btn['label']}** is incorrect! ❌\n-# {interaction.user.mention} lost 5 nerdscore")
                    increase_nerdscore(interaction.user.id, -5)
                    for child in view.children:
                        if child.custom_id == btn["custom_id"]:
                            child.disabled = True
                            child.style = discord.ButtonStyle.danger
                            break
                await interaction.message.edit(view=view)
            button = discord.ui.Button(label=btn["label"], style=discord.ButtonStyle.primary, custom_id=btn["custom_id"])
            button.callback = callback
            view.add_item(button)
        try:
            await interaction.followup.send(f"### ❔ Trivia\nGenre: {genre}\nDifficulty: {difficulty}\n> {args['question']}", view=view)
        except:
            await interaction.followup.send("An error occurred while creating the trivia question. Please try again.")
            return

    @fun_group.command(name="tictactoe", description="Play a game of Tic Tac Toe")
    async def tictactoe(interaction: Interaction):
        player = interaction.user
        class TicTacToeView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
                self.board = [None] * 9
                self.current_turn = "player"
                self.message = None

                for i in range(9):
                    self.add_item(TicTacToeButton(i, self))

            def check_winner(self):
                winning_combinations = [
                    (0, 1, 2), (3, 4, 5), (6, 7, 8),
                    (0, 3, 6), (1, 4, 7), (2, 5, 8),
                    (0, 4, 8), (2, 4, 6)
                ]
                for a, b, c in winning_combinations:
                    if self.board[a] is not None and self.board[a] == self.board[b] == self.board[c]:
                        return self.board[a]
                if all(cell is not None for cell in self.board):
                    return "tie"
                return None

            async def player_move(self, idx: int, button: discord.ui.Button, interaction: Interaction):
                if self.current_turn != "player" or self.board[idx] is not None:
                    return
                self.board[idx] = "player"
                button.label = "X"
                button.disabled = True
                button.style = discord.ButtonStyle.danger
                winner = self.check_winner()
                if winner:
                    for child in self.children:
                        child.disabled = True
                    if winner == "tie":
                        content = "### ❌⭕ Tic Tac Toe\nIt's a tie!"
                    else:
                        content = f"### ❌ Tic Tac Toe\n{player.display_name} wins!\n-# You earned 10 nerdscore"
                        increase_nerdscore(interaction.user.id, 10)
                    return await interaction.response.edit_message(content=content, view=self)
                self.current_turn = "ai"
                await interaction.response.edit_message(view=self)
                await self.ai_move(interaction, self.message)

            async def ai_move(self, interaction: Interaction, message):
                await message.edit(content="### ⭕ Tic Tac Toe\nAI Nerd 2 is making its move...", view=self)
                messages = [
                    {'role': 'system', 'content': """You are an agent designed to play Tic Tac Toe. The board is a 3x3 grid represented as a flat list of 9 elements, where:
Index 0-2 = top row
Index 3-5 = middle row
Index 6-8 = bottom row
Each element can be:
None = empty
'player' = occupied by the player
'ai' = occupied by you (the AI)
Respond only with the index (0-8) of a valid empty cell where you choose to play your next move.
Do not respond with anything else.
Current board state: """ + str(self.board)}
                ]
                if DEBUG:
                    print('--- TICTACTOE REQUEST ---')
                    print(json.dumps(messages, ensure_ascii=False, indent=2))
                completion = await generate_response(
                    messages,
                    tools=None,
                    tool_choice=None,
                    effort="low",
                    model=COMMANDS_MODEL,
                    user = f"tictactoe_{interaction.user.name}:{interaction.user.id}"
                )
                msg_obj = completion.output_text
                if DEBUG:
                    print('--- RESPONSE ---')
                    print(msg_obj)
                ai_choice = int(msg_obj)
                self.board[ai_choice] = "ai"
                for child in self.children:
                    if child.custom_id == f"ttt_{ai_choice+1}":
                        child.label = "O"
                        child.disabled = True
                        child.style = discord.ButtonStyle.primary
                        break
                winner = self.check_winner()
                if winner:
                    for child in self.children:
                        child.disabled = True
                    if winner == "tie":
                        content = "### ❌⭕ Tic Tac Toe\nIt's a tie!"
                    else:
                        content = "### ⭕ Tic Tac Toe\nAI Nerd 2 wins!\n-# You lost 10 nerdscore"
                        increase_nerdscore(interaction.user.id, -5)
                    return await message.edit(content=content, view=self)
                self.current_turn = "player"
                await message.edit(content="### ❌ Tic Tac Toe\n**Click a button to make your move!**", view=self)

        class TicTacToeButton(discord.ui.Button):
            def __init__(self, index: int, view_ref: TicTacToeView):
                super().__init__(label="\u200b", style=discord.ButtonStyle.secondary, custom_id=f"ttt_{index+1}", row=index//3)
                self.index = index
                self.view_ref = view_ref

            async def callback(self, interaction: Interaction):
                if interaction.user != player:
                    await interaction.response.send_message("This isn't your game.", ephemeral=True)
                    return
                if self.view_ref.current_turn != "player":
                    await interaction.response.send_message("Wait for your turn.", ephemeral=True)
                    return
                await self.view_ref.player_move(self.index, self, interaction)

        view = TicTacToeView()
        if random.random() < 0.5:
            msg = await interaction.response.send_message("### ⭕ Tic Tac Toe\nAI Nerd 2 is making its move...", view=view)
            view.message = await interaction.original_response()
            view.current_turn = "ai"
            await view.ai_move(interaction, view.message)
        else:
            msg = await interaction.response.send_message("### ❌ Tic Tac Toe\n**Click a button to make your move!**", view=view)
            view.message = await interaction.original_response()

    @fun_group.command(name="nerdscore", description="Show someone's nerdscore")
    @app_commands.describe(user="The user to check nerdscore for")
    async def nerdscore(interaction: Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user
        await interaction.response.defer()
        score = get_nerdscore(user.id)
        await interaction.followup.send(f"### 🤓 {user.display_name}'s Nerdscore\n**{str(score)}**")
    
    @fun_group.command(name="nerdscore-leaderboard", description="Show leaderboard of top 10 users with highest nerdscore")
    async def nerdscore_leaderboard(interaction: Interaction):
        await interaction.response.defer()
        scores = load_nerdscore()
        sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top10 = sorted_scores[:10]
        leaderboard_lines = []
        for rank, (user_id, score) in enumerate(top10, start=1):
            user = await bot.fetch_user(int(user_id))
            leaderboard_lines.append(f"{rank}. {user.name} - {score}")
        leaderboard_str = "\n".join(leaderboard_lines) if leaderboard_lines else "No scores yet."
        await interaction.followup.send(f"### 📊 Nerdscore Leaderboard\n{leaderboard_str}")

    @fun_group.command(name="dailyquiz", description="Take the daily quiz to earn 500 nerdscore (one per day)")
    async def dailyquiz(interaction: Interaction):
        await interaction.response.defer()
        records = load_daily_quiz_records()
        user_id = str(interaction.user.id)
        today = datetime.datetime.utcnow().date().isoformat()

        if records.get(user_id) == today:
            return await interaction.followup.send("You have already taken today's quiz. Try again tomorrow!")

        properties = {
            'question': {'type': 'string'},
            'correct_answer': {'type': 'string'}
        }
        property_names = ['question', 'correct_answer']
        tools = [
            {
                'name': 'create_trivia',
                'description': 'Create a trivia question',
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                    'required': property_names
                }
            }
        ]

        questions_data = load_recent_questions()
        if user_id not in questions_data:
            questions_data[user_id] = {}

        genre_counts = {}
        for g, lst in questions_data[user_id].items():
            if isinstance(lst, list) and len(lst) > 0:
                genre_counts[g] = genre_counts.get(g, 0) + len(lst)

        if genre_counts:
            top_genre = max(genre_counts.items(), key=lambda x: x[1])[0]
        else:
            top_genre = "Any"
        user_recent = questions_data[user_id][top_genre]

        MAX_RETRIES = 3
        quiz_question = None
        skip_similarity = False
        for attempt in range(MAX_RETRIES):
            messages = [
                {
                    'role': 'developer',
                    'content': (
                        "You are an agent designed to generate trivia questions for a daily quiz. "
                        "Create one question with a short correct answer. "
                        "Do not include any extra information.\n"
                        f"Question genre: {top_genre}"
                    )
                }
            ]

            if attempt >= 2:
                skip_similarity = True
                prev_qs = [p.get('q') for p in user_recent[-50:] if p.get('q')]
                if prev_qs:
                    exclusion_text = (
                        "Do not reuse any of these previous questions (exact or paraphrased):\n"
                        + "\n".join(f"- {q}" for q in prev_qs)
                    )
                    messages.append({'role': 'developer', 'content': exclusion_text})

            if DEBUG:
                print('--- DAILY QUIZ REQUEST ---')
                print(json.dumps(messages, ensure_ascii=False, indent=2))

            completion = await generate_response(
                messages,
                tools=tools,
                tool_choice={"type": "function", "name": "create_trivia"},
                model=COMMANDS_MODEL,
                user = f"dailyquiz_{interaction.user.name}:{interaction.user.id}"
            )
            args = {}
            for item in completion.output:
                if item.type == "function_call":
                    args = json.loads(item.arguments or "{}")

            if DEBUG:
                print('--- RESPONSE ---')
                print(args)

            quiz_question = args.get("question", "")
            correct_answers = [args.get("correct_answer", "")]

            if not quiz_question:
                continue

            if skip_similarity:
                break

            new_emb = embed_text(quiz_question)
            similar = False
            for prev in user_recent:
                if "emb" not in prev:
                    continue
                score = cosine(new_emb, np.array(prev["emb"], dtype=np.float32))
                if DEBUG:
                    print(f"Cosine similarity with previous daily quiz '{prev['q']}': {score}")
                if score > 0.85:
                    similar = True
                    break
            if not similar:
                break
        else:
            await interaction.followup.send("An error occurred while creating the dailyquiz question. Please try again.")
            return

        user_recent.append({"q": quiz_question, "emb": new_emb})
        if len(user_recent) > 50:
            user_recent.pop(0)
        questions_data[user_id][top_genre] = user_recent
        save_recent_questions(questions_data)

        await interaction.followup.send(f"### 🎯 Daily Quiz\n> {quiz_question}\nType your answer now within 30 seconds!")

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        first_attempt_correct = False
        timeout = False
        try:
            reply = await interaction.client.wait_for("message", timeout=30.0, check=check)
            if any(reply.content.strip().lower() == ans.strip().lower() for ans in correct_answers):
                first_attempt_correct = True
            else:
                checkmessages = [
                    {'role': 'developer', 'content': f"""
You are checking trivia answers.
Question: "{quiz_question}"
Proposed answer: "{reply.content}"
Correct answer: "{correct_answers[0]}"
If the proposed answer means the same as the correct answer (even if the wording differs), output only: True
Otherwise output only: False
"""}
                ]
                if DEBUG:
                    print('--- DAILY QUIZ REQUEST ---')
                    print(json.dumps(checkmessages, ensure_ascii=False, indent=2))
                completion = await generate_response(checkmessages, model=COMMANDS_MODEL, user=f"dailyquiz_{interaction.user.name}:{interaction.user.id}")
                if DEBUG:
                    print('--- RESPONSE ---')
                    print(completion.output_text)
                first_attempt_correct = completion.output_text.strip() == "True"
        except asyncio.TimeoutError:
            timeout = True

        records[user_id] = today
        save_daily_quiz_records(records)

        if first_attempt_correct:
            increase_nerdscore(interaction.user.id, 500)
            await interaction.followup.send("Correct! You earned 500 nerdscore.")
            return

        class RetryView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.retry_used = False
            @discord.ui.button(label="Retry", style=discord.ButtonStyle.primary, custom_id="dailyquiz_retry")
            async def retry_button(self, interaction: Interaction, button: discord.ui.Button):
                if get_nerdscore(interaction.user.id) < 250:
                    await interaction.response.send_message("You need at least 250 nerdscore to retry.", ephemeral=True)
                    return
                await interaction.response.defer(thinking=True)
                self.retry_used = True
                button.disabled = True
                await interaction.message.edit(view=self)

                for _ in range(MAX_RETRIES):
                    if DEBUG:
                        print('--- DAILY QUIZ REQUEST ---')
                        print(json.dumps(messages, ensure_ascii=False, indent=2))
                    completion = await generate_response(
                        messages,
                        tools=tools,
                        tool_choice={"type": "function", "name": "create_trivia"},
                        model=COMMANDS_MODEL,
                        user = f"dailyquiz_{interaction.user.name}:{interaction.user.id}"
                    )
                    args = {}
                    for item in completion.output:
                        if item.type == "function_call":
                            args = json.loads(item.arguments or "{}")
                    if DEBUG:
                        print('--- RESPONSE ---')
                        print(args)
                    quiz_question = args.get("question", "")
                    correct_answers = [args.get("correct_answer", "")]
                    if not quiz_question:
                        continue
                    new_emb = embed_text(quiz_question)
                    similar = False
                    for prev in user_recent:
                        if "emb" not in prev:
                            continue
                        score = cosine(new_emb, np.array(prev["emb"], dtype=np.float32))
                        if score > 0.85:
                            similar = True
                            break
                    if not similar:
                        break
                else:
                    await interaction.followup.send("An error occurred while creating the dailyquiz question.")
                    self.stop()
                    return
                
                increase_nerdscore(interaction.user.id, -250)

                user_recent.append({"q": quiz_question, "emb": new_emb})
                if len(user_recent) > 50:
                    user_recent.pop(0)
                questions_data[user_id][top_genre] = user_recent
                save_recent_questions(questions_data)

                await interaction.followup.send(f"-# You bought a retry for 250 nerdscore\n### 🎯 Daily Quiz\n> {quiz_question}\nType your answer now within 30 seconds!")
                try:
                    retry_reply = await interaction.client.wait_for("message", timeout=30.0, check=check)
                except asyncio.TimeoutError:
                    await interaction.followup.send(f"Time's up! The correct answer was: **{correct_answers[0]}**")
                    self.stop()
                    return
                if any(retry_reply.content.strip().lower() == ans.strip().lower() for ans in correct_answers):
                    increase_nerdscore(interaction.user.id, 500)
                    await interaction.followup.send("Correct! You earned 500 nerdscore.")
                else:
                    checkmessages = [
                        {'role': 'developer', 'content': f"""
You are checking trivia answers.
Question: "{quiz_question}"
Proposed answer: "{retry_reply.content}"
Correct answer: "{correct_answers[0]}"
If the proposed answer means the same as the correct answer (even if the wording differs), output only: True
Otherwise output only: False
"""}
                    ]
                    if DEBUG:
                        print('--- DAILY QUIZ REQUEST ---')
                        print(json.dumps(checkmessages, ensure_ascii=False, indent=2))
                    completion = await generate_response(checkmessages, model=COMMANDS_MODEL, user=f"dailyquiz_{interaction.user.name}:{interaction.user.id}")
                    if DEBUG:
                        print('--- RESPONSE ---')
                        print(completion.output_text)
                    if completion.output_text.strip() == "True":
                        increase_nerdscore(interaction.user.id, 500)
                        await interaction.followup.send("Correct! You earned 500 nerdscore.")
                    else:
                        await interaction.followup.send(f"Incorrect! The correct answer was: **{correct_answers[0]}**")
                records[user_id] = today
                save_daily_quiz_records(records)
                self.stop()

        view = RetryView()
        msg_text = f"Time's up! The correct answer was: **{correct_answers[0]}**" if timeout else f"Incorrect! The correct answer was: **{correct_answers[0]}**"
        msg_text += "\nWould you like to retry by paying 250 nerdscore?"
        await interaction.followup.send(msg_text, view=view)
        await view.wait()
        if not view.retry_used:
            records[user_id] = today
            save_daily_quiz_records(records)


    bot.tree.add_command(fun_group)

    admin_group = app_commands.Group(name="admin", description="Admin commands")

    @admin_group.command(name="restart", description="Restart the bot")
    async def restart(interaction: Interaction):
        if interaction.user.id == OWNER_ID:
            await interaction.response.send_message("Restarting...", ephemeral=True)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)

    @admin_group.command(name="stats", description="Show detailed bot statistics with graphs")
    async def stats(interaction: Interaction):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # System metrics
        proc = psutil.Process(os.getpid())
        bot_cpu_usage = proc.cpu_percent(interval=5)
        latency_ms = round(interaction.client.latency * 1000, 2)
        bot_ram_usage = proc.memory_info().rss / (1024 * 1024)
        try:
            uptime_seconds = time.time() - proc.create_time()
        except Exception:
            uptime_seconds = 0

        server_count = len(bot.guilds)
        try:
            metrics_data = storage.load_user_metrics() or {}
            user_count_from_file = len(metrics_data)
        except Exception:
            user_count_from_file = 0

        # Record metrics for history tracking
        try:
            messages_sent = int(metrics.messages_sent._value.get())
        except Exception:
            messages_sent = "N/A"
        
        try:
            metrics.record_daily_metrics(
                servers=server_count,
                users=user_count_from_file,
                messages=int(messages_sent) if isinstance(messages_sent, int) else 0
            )
        except Exception as e:
            if DEBUG:
                print(f"Error recording metrics: {e}")

        # Nerdscore data
        try:
            scores = load_nerdscore()
            nerdscore_users = len(scores)
            total_nerdscore = sum(scores.values()) if isinstance(scores, dict) else 0
            top10 = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:10]
            top10_lines = []
            for rank, (user_id, score) in enumerate(top10, start=1):
                try:
                    user = await bot.fetch_user(int(user_id))
                    name = user.name
                except Exception:
                    name = f"id:{user_id}"
                top10_lines.append(f"{rank}. {name} - {score}")
            top10_str = "\n".join(top10_lines) if top10_lines else "No nerdscore data"
        except Exception:
            nerdscore_users = 0
            total_nerdscore = 0
            top10_str = "N/A"

        # Get storage data
        daily_messages = storage.load_daily_counts() or {}
        recent_freewill = storage.get_freewill_attempts() or {}
        recent_questions = storage.load_recent_questions() or {}
        serversettings = storage.load_settings() or {}
        daily_quiz = storage.load_daily_quiz_records() or {}
        user_metrics = storage.load_user_metrics() or {}

        try:
            daily_avg_active = "N/A"
            if isinstance(daily_messages, dict):
                date_keys = [k for k in daily_messages.keys() if not str(k).startswith('_')]
                if date_keys:
                    latest_date = sorted(date_keys)[-1]
                    latest_data = daily_messages.get(latest_date) or {}
                    counts = []
                    for v in latest_data.values():
                        try:
                            c = int(v)
                        except Exception:
                            continue
                        if c > 0:
                            counts.append(c)
                    if counts:
                        daily_avg_active = f"{(sum(counts) / len(counts)):.2f}"
                    else:
                        daily_avg_active = "0.00"
        except Exception:
            daily_avg_active = "N/A"

        try:
            avg_total_messages = "N/A"
            if isinstance(user_metrics, dict) and user_metrics:
                totals = []
                for val in user_metrics.values():
                    if isinstance(val, dict):
                        m = val.get('messages') or val.get('message') or 0
                        try:
                            totals.append(int(m))
                        except Exception:
                            continue
                    else:
                        try:
                            totals.append(int(val))
                        except Exception:
                            continue
                if totals:
                    avg_total_messages = f"{(sum(totals) / len(totals)):.2f}"
                else:
                    avg_total_messages = "0.00"
        except Exception:
            avg_total_messages = "N/A"

        try:
            from memory import get_all_summaries, _read_json_encrypted
            all_summaries = get_all_summaries() or []
            memory_count = len(all_summaries)
            try:
                user_mem_data = _read_json_encrypted('user_memories_enc') or {}
                user_mem_count = len(user_mem_data.keys()) if isinstance(user_mem_data, dict) else 0
            except Exception:
                user_mem_count = "N/A"
        except Exception:
            memory_count = "N/A"
            user_mem_count = "N/A"

        # Get growth stats
        growth_stats = metrics.get_growth_stats()

        # Create embeds
        embeds = []
        
        # System Status Embed
        system_embed = discord.Embed(
            title="🖥️ System Status",
            color=discord.Color.blue(),
            description="Current bot performance and resource usage"
        )
        system_embed.add_field(name="Latency", value=f"{latency_ms} ms", inline=True)
        system_embed.add_field(name="CPU Usage", value=f"{bot_cpu_usage}%", inline=True)
        system_embed.add_field(name="RAM Usage", value=f"{bot_ram_usage:.2f} MB", inline=True)
        system_embed.add_field(name="Uptime", value=f"{int(uptime_seconds)} seconds ({int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m)", inline=True)
        embeds.append(system_embed)

        # Server & User Growth Embed
        growth_embed = discord.Embed(
            title="📊 Growth Metrics",
            color=discord.Color.green(),
            description="Current and historical growth data"
        )
        growth_embed.add_field(name="Current Servers", value=f"**{server_count}**", inline=True)
        growth_embed.add_field(name="Current Users", value=f"**{user_count_from_file}**", inline=True)
        growth_embed.add_field(name="Messages Tracked", value=f"**{messages_sent}**", inline=True)
        
        if growth_stats.get("available"):
            weekly_servers = growth_stats.get("weekly", {}).get("servers", 0)
            weekly_servers_pct = growth_stats.get("weekly", {}).get("servers_pct", 0)
            weekly_users = growth_stats.get("weekly", {}).get("users", 0)
            weekly_users_pct = growth_stats.get("weekly", {}).get("users_pct", 0)
            
            server_emoji = "📈" if weekly_servers >= 0 else "📉"
            user_emoji = "📈" if weekly_users >= 0 else "📉"
            
            growth_embed.add_field(
                name="Weekly Growth",
                value=f"{server_emoji} Servers: {weekly_servers:+d} ({weekly_servers_pct:+.1f}%)\n{user_emoji} Users: {weekly_users:+d} ({weekly_users_pct:+.1f}%)",
                inline=False
            )
            
            monthly_servers = growth_stats.get("monthly", {}).get("servers", 0)
            monthly_servers_pct = growth_stats.get("monthly", {}).get("servers_pct", 0)
            monthly_users = growth_stats.get("monthly", {}).get("users", 0)
            monthly_users_pct = growth_stats.get("monthly", {}).get("users_pct", 0)
            
            server_emoji = "📈" if monthly_servers >= 0 else "📉"
            user_emoji = "📈" if monthly_users >= 0 else "📉"
            
            growth_embed.add_field(
                name="Monthly Growth",
                value=f"{server_emoji} Servers: {monthly_servers:+d} ({monthly_servers_pct:+.1f}%)\n{user_emoji} Users: {monthly_users:+d} ({monthly_users_pct:+.1f}%)",
                inline=False
            )
        
        embeds.append(growth_embed)

        # Engagement Embed
        engagement_embed = discord.Embed(
            title="💬 Engagement",
            color=discord.Color.gold(),
            description="Message and activity statistics"
        )
        engagement_embed.add_field(name="Avg Daily Messages (Latest)", value=daily_avg_active, inline=True)
        engagement_embed.add_field(name="Avg Messages per User", value=avg_total_messages, inline=True)
        engagement_embed.add_field(name="Daily Message Records", value=len(daily_messages), inline=True)
        embeds.append(engagement_embed)

        # Nerdscore Embed
        nerdscore_embed = discord.Embed(
            title="🤓 Nerdscore Rankings",
            color=discord.Color.purple(),
            description="Top performers in the nerdscore system"
        )
        nerdscore_embed.add_field(name="Participating Users", value=f"**{nerdscore_users}**", inline=True)
        nerdscore_embed.add_field(name="Total Points", value=f"**{total_nerdscore}**", inline=True)
        nerdscore_embed.add_field(name="Top 10", value=top10_str, inline=False)
        embeds.append(nerdscore_embed)

        # Data Storage Embed
        storage_embed = discord.Embed(
            title="💾 Data Storage",
            color=discord.Color.greyple(),
            description="Information about stored data"
        )
        storage_embed.add_field(name="Memory Summaries", value=memory_count, inline=True)
        storage_embed.add_field(name="Users with Memories", value=user_mem_count, inline=True)
        storage_embed.add_field(name="Quiz Records", value=len(daily_quiz), inline=True)
        storage_embed.add_field(name="Server Settings", value=len(serversettings), inline=True)
        storage_embed.add_field(name="User Metrics", value=len(user_metrics), inline=True)
        storage_embed.add_field(name="Freewill Entries", value=len(recent_freewill), inline=True)
        storage_embed.add_field(name="Recent Questions", value=len(recent_questions), inline=True)
        embeds.append(storage_embed)

        # Send embeds
        await interaction.followup.send(embeds=embeds, ephemeral=True)

        # Try to generate and send graphs
        try:
            combined_graph = metrics.generate_combined_graph(days=30)
            if combined_graph:
                await interaction.followup.send(file=discord.File(combined_graph, filename="growth_30d.png"), ephemeral=True)
        except Exception as e:
            if DEBUG:
                print(f"Error generating combined graph: {e}")

    @admin_group.command(name="stats-graphs", description="Show detailed statistical graphs")
    @app_commands.describe(days="Number of days to show (7, 14, 30, 60, 90)", metric="Which metric to graph")
    @app_commands.choices(days=[
        app_commands.Choice(name="Last 7 Days", value="7"),
        app_commands.Choice(name="Last 14 Days", value="14"),
        app_commands.Choice(name="Last 30 Days", value="30"),
        app_commands.Choice(name="Last 60 Days", value="60"),
        app_commands.Choice(name="Last 90 Days", value="90"),
    ], metric=[
        app_commands.Choice(name="Servers", value="servers"),
        app_commands.Choice(name="Users", value="users"),
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="All Growth Metrics", value="combined"),
    ])
    async def stats_graphs(interaction: Interaction, days: str = "30", metric: str = "combined"):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        days_int = int(days)
        
        try:
            if metric == "combined":
                graph_buffer = metrics.generate_combined_graph(days=days_int)
                if graph_buffer:
                    await interaction.followup.send(
                        file=discord.File(graph_buffer, filename=f"growth_{days_int}d.png"),
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send("Could not generate graph. Make sure matplotlib is installed.", ephemeral=True)
            else:
                graph_buffer = metrics.generate_graph(metric_type=metric, days=days_int)
                if graph_buffer:
                    metric_name = metric.replace('_', ' ').title()
                    await interaction.followup.send(
                        file=discord.File(graph_buffer, filename=f"{metric}_{days_int}d.png"),
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send("Could not generate graph. Ensure there is historical data available.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error generating graph: {str(e)}", ephemeral=True)
            if DEBUG:
                print(f"Graph generation error: {e}")

    @admin_group.command(name="ban", description="Ban or unban a user")
    @app_commands.describe(action="Choose ban or unban", user="The user to affect")
    @app_commands.choices(action=[
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Unban", value="unban"),
    ])
    async def ban_toggle(interaction: Interaction, action: str, user: discord.User):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        try:
            banned_map = storage.load_banned_map() or {}
        except Exception:
            banned_map = {}

        uid = int(user.id)
        if action == 'ban':
            if uid in banned_map:
                return await interaction.response.send_message(f"{user} is already banned.", ephemeral=True)
            banned_map[uid] = {'notified': False}
            try:
                storage.save_banned_map(banned_map)
                abuse_detection.clear_user_tracking(uid)
            except Exception:
                return await interaction.response.send_message("Failed to save banned users list.", ephemeral=True)
            await interaction.response.send_message(f"Banned {user} from using the bot.", ephemeral=True)
        else:
            if uid not in banned_map:
                return await interaction.response.send_message(f"{user} is not banned.", ephemeral=True)
            try:
                banned_map.pop(uid, None)
                storage.save_banned_map(banned_map)
            except Exception:
                return await interaction.response.send_message("Failed to update banned users list.", ephemeral=True)
            await interaction.response.send_message(f"Unbanned {user}.", ephemeral=True)

    @admin_group.command(name="abuse-dashboard", description="View and manage suspicious user activity")
    async def abuse_dashboard(interaction: Interaction):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        suspicious_users = abuse_detection.get_top_suspicious_users(limit=15)
        stats = abuse_detection.get_stats()
        
        if not suspicious_users:
            await interaction.followup.send("No suspicious activity detected.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Abuse Detection Dashboard",
            description=f"Total tracked users: {stats['total_tracked_users']} | High risk: {stats['high_risk_users']}",
            color=discord.Color.orange()
        )
        
        for i, user_data in enumerate(suspicious_users[:10], 1):
            user_id = user_data['user_id']
            user = await bot.fetch_user(user_id)
            name = user.name
            score = user_data['score']
            messages_24h = user_data['last_24h_messages']
            empty = user_data['empty_messages']
            duplicates = user_data['duplicate_messages']
            rapid = user_data['rapid_fire_count']
            mph = user_data['messages_per_hour']
            
            risk = "🔴 CRITICAL" if score > 100 else "🟠 HIGH" if score > 50 else "🟡 MEDIUM" if score > 25 else "🟢 LOW"
            
            field_value = (
                f"**Score:** {score} {risk}\n"
                f"**24h Messages:** {messages_24h}\n"
                f"**Empty:** {empty} | **Duplicates:** {duplicates} | **Spam bursts:** {rapid}\n"
                f"**Messages/hour:** {mph}"
            )
            embed.add_field(name=f"#{i} - {name} ({user_id})", value=field_value, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_group.command(name="user-abuse-detail", description="View detailed abuse tracking for a user")
    @app_commands.describe(user="The user to check")
    async def user_abuse_detail(interaction: Interaction, user: discord.User):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        abuse_score = abuse_detection.calculate_abuse_score(user.id)
        message_history = abuse_detection.get_user_message_history(user.id, limit=30)
        
        if not message_history:
            await interaction.followup.send(f"No tracking data found for user {user.id}.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"Abuse Details For User {user.name} ({user.id})",
            color=discord.Color.red() if abuse_score['score'] > 100 else discord.Color.orange() if abuse_score['score'] > 50 else discord.Color.yellow() if abuse_score['score'] > 25 else discord.Color.green()
        )
        
        embed.add_field(name="Abuse Score", value=f"`{abuse_score['score']}`", inline=True)
        embed.add_field(name="Messages (24h)", value=f"`{abuse_score['last_24h_messages']}`", inline=True)
        embed.add_field(name="Messages/hour", value=f"`{abuse_score['messages_per_hour']}`", inline=True)
        embed.add_field(name="Empty Messages", value=f"`{abuse_score['empty_messages']}`", inline=True)
        embed.add_field(name="Duplicates", value=f"`{abuse_score['duplicate_messages']}`", inline=True)
        embed.add_field(name="Spam Bursts", value=f"`{abuse_score['rapid_fire_count']}`", inline=True)
        
        recent_lengths = [str(h['content_len']) for h in message_history[:10]]
        embed.add_field(name="Recent Message Lengths", value=f"`{' '.join(recent_lengths)}`", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    bot.tree.add_command(admin_group)