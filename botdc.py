# ===== MAIN BOT FILE =====
# File: bot.py

import discord
from discord.ext import commands
import asyncio
import yt_dlp
from collections import deque

# Konfigurasi bot
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Queue musik per guild
music_queues = {}

# Konfigurasi yt-dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'youtube_include_dash_manifest': False,
    'extract_flat': False,
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# ================================================
# CLASS: YTDLSource
# ================================================
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url', data.get('url'))
        self.duration = data.get('duration')

    @classmethod
    async def from_info(cls, data, *, loop=None, stream=True):
        """Langsung gunakan data dari yt_dlp.extract_info, tanpa extract ulang"""
        if stream:
            filename = data['url']
        else:
            filename = ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

# ================================================
# CLASS: MusicPlayer
# ================================================
class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.queue = deque()
        self.current = None
        self.voice_client = None

    async def play_next(self):
        if len(self.queue) > 0:
            data = self.queue.popleft()
            self.current = await YTDLSource.from_info(data, loop=self.bot.loop, stream=True)
            self.voice_client.play(
                self.current,
                after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
            )
            await self.channel.send(f'🎵 Sekarang memutar: **{self.current.title}**')
        else:
            self.current = None

    async def add_to_queue(self, data):
        self.queue.append(data)

# ================================================
# EVENT: on_ready
# ================================================
@bot.event
async def on_ready():
    print(f'✅ Bot {bot.user.name} telah online!')
    print(f'🆔 Bot ID: {bot.user.id}')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, 
        name="!play <lagu>"
    ))

# ================================================
# COMMAND: !play
# ================================================
@bot.command(name='play', help='Putar lagu dari YouTube')
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send('❌ Anda harus berada di voice channel terlebih dahulu!')
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        voice_client = await channel.connect()
    else:
        voice_client = ctx.voice_client

    if ctx.guild.id not in music_queues:
        music_queues[ctx.guild.id] = MusicPlayer(ctx)
        music_queues[ctx.guild.id].voice_client = voice_client

    player = music_queues[ctx.guild.id]

    if not query.startswith('http'):
        query = f'ytsearch:{query}'

    await ctx.send(f'🔍 Mencari: **{query.replace("ytsearch:", "")}**')

    try:
        info = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if 'entries' in info:
            info = info['entries'][0]

        title = info.get('title', 'Unknown Title')
        await player.add_to_queue(info)

        if not voice_client.is_playing() and player.current is None:
            await asyncio.sleep(1)  # delay kecil biar voice stabil
            await player.play_next()
        else:
            await ctx.send(f'➕ Ditambahkan ke antrian: **{title}**')

    except Exception as e:
        import traceback
        traceback.print_exc()
        await ctx.send(f'❌ Terjadi error: {str(e)}')

# ================================================
# COMMAND: !pause
# ================================================
@bot.command(name='pause', help='Jeda lagu')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send('⏸️ Lagu dijeda.')
    else:
        await ctx.send('❌ Tidak ada lagu yang sedang diputar.')

# ================================================
# COMMAND: !resume
# ================================================
@bot.command(name='resume', help='Lanjutkan lagu')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send('▶️ Lagu dilanjutkan.')
    else:
        await ctx.send('❌ Lagu tidak sedang dijeda.')

# ================================================
# COMMAND: !skip
# ================================================
@bot.command(name='skip', help='Skip lagu')
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send('⏭️ Lagu di-skip.')
    else:
        await ctx.send('❌ Tidak ada lagu yang sedang diputar.')

# ================================================
# COMMAND: !stop
# ================================================
@bot.command(name='stop', help='Stop musik dan keluar dari voice channel')
async def stop(ctx):
    if ctx.guild.id in music_queues:
        player = music_queues[ctx.guild.id]
        player.queue.clear()
        del music_queues[ctx.guild.id]
    
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send('⏹️ Musik dihentikan dan bot keluar dari voice channel.')
    else:
        await ctx.send('❌ Bot tidak ada di voice channel.')

# ================================================
# COMMAND: !queue
# ================================================
@bot.command(name='queue', help='Lihat antrian lagu')
async def queue(ctx):
    if ctx.guild.id not in music_queues:
        await ctx.send('📭 Antrian kosong.')
        return

    player = music_queues[ctx.guild.id]
    if len(player.queue) == 0:
        await ctx.send('📭 Antrian kosong.')
        return

    queue_list = "📃 **Antrian Lagu:**\n"
    for i, data in enumerate(list(player.queue)[:10], 1):
        queue_list += f"{i}. {data.get('title', 'Unknown Title')}\n"

    if len(player.queue) > 10:
        queue_list += f"... dan {len(player.queue) - 10} lagu lainnya"

    await ctx.send(queue_list)

# ================================================
# COMMAND: !np
# ================================================
@bot.command(name='np', help='Lagu yang sedang diputar')
async def now_playing(ctx):
    if ctx.guild.id in music_queues:
        player = music_queues[ctx.guild.id]
        if player.current:
            await ctx.send(f'🎵 Sedang diputar: **{player.current.title}**')
            return

    await ctx.send('❌ Tidak ada lagu yang sedang diputar.')

# ================================================
# COMMAND: !commands
# ================================================
@bot.command(name='commands', help='Tampilkan semua perintah')
async def show_commands(ctx):
    help_text = """
🎵 **Perintah Bot Musik**

`!play <url/judul>` - Putar lagu dari YouTube
`!pause` - Jeda lagu
`!resume` - Lanjutkan lagu
`!skip` - Skip ke lagu berikutnya
`!stop` - Stop dan keluar dari voice channel
`!queue` - Lihat antrian lagu
`!np` - Lihat lagu yang sedang diputar
`!volume` - Untuk mengatur volume lagu
`!commands` - Tampilkan pesan ini


**Contoh penggunaan:**
`!play despacito`
`!play https://www.youtube.com/watch?v=VIDEO_ID`
    """
    await ctx.send(help_text)
# ================================================
# COMMAND: !volume
# ================================================
@bot.command(name='volume', help='Atur volume suara bot (0-100)')
async def volume(ctx, volume: int):
    """Mengatur volume musik yang sedang diputar"""
    if ctx.voice_client is None or not ctx.voice_client.is_playing():
        await ctx.send("❌ Tidak ada lagu yang sedang diputar.")
        return

    if volume < 0 or volume > 100:
        await ctx.send("⚠️ Volume harus antara **0 dan 100**.")
        return

    guild_id = ctx.guild.id
    if guild_id not in music_queues or not music_queues[guild_id].current:
        await ctx.send("❌ Tidak ada lagu yang sedang diputar.")
        return

    player = music_queues[guild_id]
    player.current.volume = volume / 100.0  # ubah ke skala 0.0–1.0
    await ctx.send(f"🔊 Volume diatur ke **{volume}%**")

# ================================================
# ERROR HANDLER
# ================================================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send('❌ Perintah tidak ditemukan. Ketik `!commands` untuk melihat daftar perintah.')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('❌ Argumen tidak lengkap. Contoh: `!play judul lagu`')
    else:
        await ctx.send(f'❌ Terjadi error: {str(error)}')

# ================================================
# JALANKAN BOT
# ================================================
if __name__ == '__main__':
    TOKEN = 'MTQyODc2MDI3Njk4MjgyNTExMg.GBWoTR.Q_5p3pGEuMk2Zvjt9lOUOLFGj1LjZLcJcVXMY4'  # ⚠️ GANTI DENGAN TOKEN BOT ANDA!
    bot.run(TOKEN)
