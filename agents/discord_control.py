"""
Discord control - optional remote control via bot
Stub: full implementation in binance_future_bot; this keeps imports working.
"""
import os
import threading
from loguru import logger


class ControlState:
    def __init__(self):
        self.paused = False
        self.risk_gate = None
        self.executor = None
        self.exchange = None
        self.settings = None
        self.risk_cfg = None
        self.mode = "paper"
        self.scanner = None
        self.ml_agent = None
        self.last_cycle_info = ""

    def set_refs(self, risk_gate, executor, exchange, settings, risk_cfg, mode):
        self.risk_gate = risk_gate
        self.executor = executor
        self.exchange = exchange
        self.settings = settings
        self.risk_cfg = risk_cfg
        self.mode = mode


control_state = ControlState()


def start_discord_in_thread():
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        logger.info("Discord control disabled (no DISCORD_BOT_TOKEN)")
        return

    def _run():
        try:
            import discord
            from discord.ext import commands

            allowed = {
                x.strip()
                for x in os.getenv("DISCORD_ALLOWED_IDS", "").split(",")
                if x.strip()
            }
            prefix = os.getenv("DISCORD_PREFIX", "!")
            intents = discord.Intents.default()
            intents.message_content = True
            bot = commands.Bot(command_prefix=prefix, intents=intents)

            def _ok(ctx):
                return not allowed or str(ctx.author.id) in allowed

            @bot.event
            async def on_ready():
                logger.info(f"Discord bot ready as {bot.user}")

            @bot.command(name="pause")
            async def pause(ctx):
                if not _ok(ctx):
                    return
                control_state.paused = True
                await ctx.send("Bot PAUSED")

            @bot.command(name="resume")
            async def resume(ctx):
                if not _ok(ctx):
                    return
                control_state.paused = False
                await ctx.send("Bot RESUMED")

            @bot.command(name="status")
            async def status(ctx):
                if not _ok(ctx):
                    return
                rg = control_state.risk_gate
                info = control_state.last_cycle_info or ""
                if rg:
                    st = rg.status()
                    await ctx.send(
                        f"mode={control_state.mode} paused={control_state.paused} "
                        f"kill={st.get('kill_switch')} open={st.get('open_positions')} "
                        f"daily={st.get('daily_pnl')} | {info}"
                    )
                else:
                    await ctx.send(f"paused={control_state.paused} | {info}")

            bot.run(token)
        except Exception as e:
            logger.warning(f"Discord bot stopped: {e}")

    t = threading.Thread(target=_run, name="discord-bot", daemon=True)
    t.start()
    logger.info("Discord control thread started")
