from discord import app_commands, Interaction
import discord
import config
import json
import os
import psutil
import asyncio
import random
import time
from openai_client import generate_response
from config import DEBUG
from nerdscore import get_nerdscore, increase_nerdscore

recent_questions = []

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
            allowed.append(chan_id)
            action = "now"
        guild_settings["allowed_channels"] = allowed
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"AI Nerd will {action} respond to all messages in <#{chan_id}>.",
            ephemeral=False
        )

    @config_group.command(name="freewill-rate", description="Control how often AI Nerd 2 responds without being pinged")
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
        messages = [
            {'role': 'system', 'content': f"You are an agent designed to generate trivia questions. Create a trivia question with one correct answer and four incorrect answers. The question should be engaging and suitable for a trivia game.\nQuestion genre: {genre}\nQuestion difficulty: {difficulty}\nDo not create any of the following questions:\n{recent_questions}"},
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
                        increase_nerdscore(interaction.user.id, 5)
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
                    think=True
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

    @fun_group.command(name="nerdscore", description="Show your nerdscore")
    @app_commands.describe(user="The user to check nerdscore for")
    async def nerdscore(interaction: Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user
        await interaction.response.defer()
        score = get_nerdscore(user.id)
        await interaction.followup.send(f"### {user.display_name}'s Nerdscore\n**{str(score)}**")
    
    bot.tree.add_command(fun_group)