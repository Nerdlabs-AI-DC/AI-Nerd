from discord import app_commands, Interaction
import discord
import config
import json

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