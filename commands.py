from discord import app_commands, Interaction
import discord
import config
import json
import os
import psutil
import asyncio
import random
import time
import io
import datetime
import requests
from openai_client import generate_response, generate_image
from config import DEBUG, REASONING_MODEL, DAILY_QUIZ_FILE, RECENT_QUESTIONS_FILE, METRICS_FILE
from nerdscore import get_nerdscore, increase_nerdscore, load_nerdscore

def load_recent_questions():
    if os.path.exists(RECENT_QUESTIONS_FILE):
        with open(RECENT_QUESTIONS_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except ValueError:
                data = {}
    else:
        data = {}
    return data

def save_recent_questions(data):
    with open(RECENT_QUESTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_daily_quiz_records():
    if os.path.exists(DAILY_QUIZ_FILE):
        with open(DAILY_QUIZ_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except ValueError:
                data = {}
    else:
        data = {}
    return data

def save_daily_quiz_records(data):
    with open(DAILY_QUIZ_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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

    @config_group.command(name="freewill", description="Control how often AI Nerd 2 responds without being pinged")
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
    @app_commands.describe(timeout="Time since last message before revive message is sent", role="Role to mention for chat revive")
    async def chatrevive(interaction: Interaction, timeout: int, role: discord.Role):
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
        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)
        latency_ms = round(interaction.client.latency * 1000, 2)
        bot_ram_usage = proc.memory_info().rss / (1024 * 1024)
        try:
            with open(config.METRICS_FILE, 'r', encoding='utf-8') as f:
                metrics_data = json.load(f)
            user_count = len(metrics_data)
        except Exception:
            user_count = 0
        oai_status = requests.get("https://status.openai.com/api/v2/summary.json")
        if oai_status.status_code == 200:
            data = oai_status.json()
            status = None
            for component in data.get("components", []):
                if component["id"] == "01JMXBRMFE0V9J9X2HY3SKX399":
                    status = component["status"]
                    break
        else:
            status = "⚠️ no response"
        bot_cpu_usage = proc.cpu_percent(interval=0)
        message = (
            "### 🟢 AI Nerd 2 is online\n"
            f"> Latency: {latency_ms} ms\n"
            f"> CPU Usage: {bot_cpu_usage}%\n"
            f"> RAM Usage: {bot_ram_usage:.2f} MB\n"
            f"> AI Status: {status}\n"
            f"> Server count: {len(bot.guilds)}\n"
            f"> User count: {user_count}\n"
        )
        await interaction.followup.send(message)

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
            function_call=None,
            user_id=interaction.user.id
        )
        msg_obj = completion.choices[0].message
        if DEBUG:
            print('--- RESPONSE ---')
            print(msg_obj.content)
        await interaction.followup.send(f"### 🎱 Magic 8-ball\n**{question}**\n{msg_obj.content}")

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
        user_id = str(interaction.user.id)
        questions_data = load_recent_questions()
        user_recent = questions_data.get(user_id, [])
        
        messages = [{'role': 'system', 'content': f"You are an agent designed to generate trivia questions. Create a trivia question with one correct answer and four incorrect answers. The question should be engaging and suitable for a trivia game.\nQuestion genre: {genre}\nQuestion difficulty: {difficulty}\nDo not create any of the following questions:\n{user_recent}"}]
        search_messages = [{'role': 'system', 'content': "You are an agent tasked with gathering interesting and accurate facts that can be used to create trivia questions. Find information about the genre: " + genre}]
        if DEBUG:
            print('--- Trivia REQUEST ---')
            print(json.dumps(messages, ensure_ascii=False, indent=2))
        completion = await generate_response(
            messages,
            functions=tools,
            function_call={"name": "create_trivia"},
            user_id=interaction.user.id
        )
        msg_obj = completion.choices[0].message
        args = json.loads(msg_obj.function_call.arguments or '{}')
        
        user_recent.append(args["question"])
        if len(user_recent) > 50:
            user_recent.pop(0)
        questions_data[user_id] = user_recent
        save_recent_questions(questions_data)
        
        view = discord.ui.View()
        buttons_data = [
            {"label": args["correct_answer"], "custom_id": "correct_answer", "correct": True},
            {"label": args["incorrect_answer1"], "custom_id": "option1", "correct": False},
            {"label": args["incorrect_answer2"], "custom_id": "option2", "correct": False},
            {"label": args["incorrect_answer3"], "custom_id": "option3", "correct": False},
            {"label": args["incorrect_answer4"], "custom_id": "option4", "correct": False},
        ]
        random.shuffle(buttons_data)
        if 'genre' in args:
            genre = args['genre']
        if 'difficulty' in args:
            difficulty = args['difficulty']
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
        if DEBUG:
            print('--- RESPONSE ---')
            print(msg_obj)
        await interaction.followup.send(f"### ❔ Trivia\nGenre: {genre}\nDifficulty: {difficulty}\n> {args['question']}", view=view)
        question_time = time.monotonic()

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
                    functions=None,
                    function_call=None,
                    model=REASONING_MODEL
                )
                msg_obj = completion.choices[0].message
                if DEBUG:
                    print('--- RESPONSE ---')
                    print(msg_obj.content)
                ai_choice = int(msg_obj.content)
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
            'correct_answer1': {'type': 'string'},
            'correct_answer2': {'type': 'string'},
            'correct_answer3': {'type': 'string'},
            'correct_answer4': {'type': 'string'},
            'correct_answer5': {'type': 'string'}
        }
        property_names = ['question', 'correct_answer1', 'correct_answer2', 'correct_answer3', 'correct_answer4', 'correct_answer5']
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
        user_recent = questions_data.get(user_id, [])
        messages = [
            {'role': 'system', 'content': "You are an agent designed to generate trivia questions. Create a hard trivia question with one short correct answer. Provide five distinct variations of the correct answer, using different grammar or wording, but all conveying the same meaning. Do not include any extra information. Do not create any of the following questions:\n" + str(user_recent)},
        ]
        if DEBUG:
            print('--- DAILY QUIZ REQUEST ---')
            print(json.dumps(messages, ensure_ascii=False, indent=2))
        completion = await generate_response(
            messages,
            functions=tools,
            function_call={"name": "create_trivia"},
            user_id=interaction.user.id
        )
        msg_obj = completion.choices[0].message
        args = json.loads(msg_obj.function_call.arguments or '{}')
        quiz_question = args["question"]
        correct_answers = [
            args['correct_answer1'],
            args['correct_answer2'],
            args['correct_answer3'],
            args['correct_answer4'],
            args['correct_answer5']
        ]
        if DEBUG:
            print('--- RESPONSE ---')
            print(msg_obj)
        await interaction.followup.send(f"### 🎯 Daily Quiz\n> {quiz_question}\nType your answer now within 30 seconds!")
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        first_attempt_correct = False
        try:
            reply = await interaction.client.wait_for("message", timeout=30.0, check=check)
            if any(reply.content.strip().lower() == ans.strip().lower() for ans in correct_answers):
                first_attempt_correct = True
            else:
                timeout = False
        except asyncio.TimeoutError:
            timeout = True
            pass
        records[user_id] = today
        save_daily_quiz_records(records)
        if first_attempt_correct:
            increase_nerdscore(interaction.user.id, 500)
            await interaction.followup.send("Correct! You earned 500 nerdscore.")
            return
        else:
            # Offer the retry button
            class RetryView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=30)
                    self.retry_used = False
                @discord.ui.button(label="Retry", style=discord.ButtonStyle.primary, custom_id="dailyquiz_retry")
                async def retry_button(self, interaction: Interaction, button: discord.ui.Button):
                    if get_nerdscore(interaction.user.id) < 250:
                        await interaction.response.send_message("You need at least 250 nerdscore to retry.", ephemeral=True)
                        return
                    self.retry_used = True
                    button.disabled = True
                    increase_nerdscore(interaction.user.id, -250)
                    await interaction.message.edit(view=self)
                    if DEBUG:
                        print('--- DAILY QUIZ REQUEST ---')
                        print(json.dumps(messages, ensure_ascii=False, indent=2))
                    completion = await generate_response(
                        messages,
                        functions=tools,
                        function_call={"name": "create_trivia"},
                        user_id=interaction.user.id
                    )
                    msg_obj = completion.choices[0].message
                    args = json.loads(msg_obj.function_call.arguments or '{}')
                    quiz_question = args["question"]
                    correct_answers = [
                        args['correct_answer1'],
                        args['correct_answer2'],
                        args['correct_answer3'],
                        args['correct_answer4'],
                        args['correct_answer5']
                    ]
                    if DEBUG:
                        print('--- RESPONSE ---')
                        print(msg_obj)
                    await interaction.response.send_message(f"-# You bought a retry for 250 nerdscore\n### 🎯 Daily Quiz\n> {quiz_question}\nType your answer now within 30 seconds!")
                    try:
                        retry_reply = await interaction.client.wait_for("message", timeout=30.0, check=check)
                    except asyncio.TimeoutError:
                        await interaction.followup.send(f"Time's up! The correct answer was: **{correct_answers[0]}**")
                        self.stop()
                        return
                    if any(reply.content.strip().lower() == ans.strip().lower() for ans in correct_answers):
                        increase_nerdscore(interaction.user.id, 500)
                        await interaction.followup.send("Correct! You earned 500 nerdscore.")
                    else:
                        await interaction.followup.send(f"Incorrect! The correct answer was: **{correct_answers[0]}**")
                    records[user_id] = today
                    save_daily_quiz_records(records)
                    self.stop()
            view = RetryView()
            if timeout:
                await interaction.followup.send(f"Time's up! The correct answer was: **{correct_answers[0]}**\nWould you like to retry for 250 nerdscore?", view=view)
            else:
                await interaction.followup.send(f"Incorrect! The correct answer was: **{correct_answers[0]}**\nWould you like to retry for 250 nerdscore?", view=view)
            await view.wait()
            if not view.retry_used:
                records[user_id] = today
                save_daily_quiz_records(records)

    bot.tree.add_command(fun_group)