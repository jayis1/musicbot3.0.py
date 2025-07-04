# music.py

import discord
from discord.ext import commands
import asyncio
import yt_dlp
import logging
from googleapiclient.discovery import build
import config

# --- YTDL Options ---
ytdl_format_options = {
    "format": "bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "cookiefile": "youtube_cookie.txt" if __import__('os').path.exists("youtube_cookie.txt") else None,
    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
    "extractor_args": {"youtube": {"player_client": ["web"]}},
}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -ac 2 -ar 48000 -b:a 320k -probesize 32 -analyzeduration 0 -nostats -loglevel quiet",
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.duration = data.get("duration")
        self.thumbnail = data.get("thumbnail")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if "entries" in data:
            return [cls(discord.FFmpegPCMAudio(entry["url"], **ffmpeg_options), data=entry) for entry in data["entries"]]
        else:
            return [cls(discord.FFmpegPCMAudio(data["url"], **ffmpeg_options), data=data)]

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queues = {}
        self.search_results = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Logged in as {self.bot.user} (ID: {self.bot.user.id})")
        print("------")

    async def get_queue(self, ctx):
        if ctx.guild.id not in self.song_queues:
            self.song_queues[ctx.guild.id] = asyncio.Queue()
        return self.song_queues[ctx.guild.id]

    def create_embed(self, title, description, color=discord.Color.blurple()):
        return discord.Embed(title=title, description=description, color=color)

    @commands.command(name="join")
    async def join(self, ctx):
        if not ctx.author.voice:
            return await ctx.send(embed=self.create_embed("Error", "You are not connected to a voice channel.", discord.Color.red()))
        if ctx.voice_client:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        else:
            await ctx.author.voice.channel.connect()
        await ctx.send(embed=self.create_embed("Joined Channel", f"Joined `{ctx.author.voice.channel}`"))

    @commands.command(name="leave")
    async def leave(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send(embed=self.create_embed("Left Channel", "Successfully disconnected from the voice channel."))

    @commands.command(name="search")
    async def search(self, ctx, *, query):
        if not config.YOUTUBE_API_KEY:
            return await ctx.send(embed=self.create_embed("Error", "YouTube API key is not set.", discord.Color.red()))
        try:
            youtube = build("youtube", "v3", developerKey=config.YOUTUBE_API_KEY)
            search_response = youtube.search().list(q=query, part="snippet", maxResults=10, type="video").execute()
            videos = [(item["snippet"]["title"], item["id"]["videoId"]) for item in search_response.get("items", [])]
            if not videos:
                return await ctx.send(embed=self.create_embed("No Results", "No songs found for your query.", discord.Color.orange()))
            self.search_results[ctx.guild.id] = videos
            response = "\n".join(f"**{i+1}.** {title}" for i, (title, _) in enumerate(videos))
            await ctx.send(embed=self.create_embed("Search Results", response))
        except Exception as e:
            await ctx.send(embed=self.create_embed("Search Error", f"An error occurred: {e}", discord.Color.red()))

    @commands.command(name="play")
    async def play(self, ctx, *, query):
        queue = await self.get_queue(ctx)
        try:
            if query.isdigit() and ctx.guild.id in self.search_results:
                video_id = self.search_results[ctx.guild.id][int(query) - 1][1]
                url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                url = query

            async with ctx.typing():
                players = await YTDLSource.from_url(url, loop=self.bot.loop)
                for player in players:
                    await queue.put(player)
                
                if len(players) > 1:
                    await ctx.send(embed=self.create_embed("Playlist Added", f"Added {len(players)} songs to the queue."))
                else:
                    await ctx.send(embed=self.create_embed("Song Added", f"Added `{players[0].title}` to the queue."))

            if not ctx.voice_client.is_playing():
                await self.play_next(ctx)
        except Exception as e:
            await ctx.send(embed=self.create_embed("Error", f"An error occurred: {e}", discord.Color.red()))

    async def play_next(self, ctx):
        queue = await self.get_queue(ctx)
        if not queue.empty() and ctx.voice_client:
            player = await queue.get()
            ctx.voice_client.play(player, after=lambda e: self.bot.loop.create_task(self.play_next(ctx)))
            await self.nowplaying(ctx, silent=True)

    @commands.command(name="volume")
    async def volume(self, ctx, volume: int):
        if ctx.voice_client and ctx.voice_client.source:
            if 0 <= volume <= 200:
                ctx.voice_client.source.volume = volume / 100
                await ctx.send(embed=self.create_embed("Volume Control", f"Volume set to {volume}%"))
            else:
                await ctx.send(embed=self.create_embed("Volume Error", "Volume must be between 0 and 200.", discord.Color.red()))

    @commands.command(name="nowplaying")
    async def nowplaying(self, ctx, silent=False):
        if ctx.voice_client and ctx.voice_client.source:
            player = ctx.voice_client.source
            queue = await self.get_queue(ctx)
            embed = self.create_embed("Now Playing", f"[{player.title}]({player.url})")
            embed.set_thumbnail(url=player.thumbnail)
            embed.add_field(name="Duration", value=f"{player.duration // 60}:{player.duration % 60:02d}")
            embed.add_field(name="Queue", value=f"{queue.qsize()} songs remaining")
            if not silent:
                await ctx.send(embed=embed)
        elif not silent:
            await ctx.send(embed=self.create_embed("Not Playing", "The bot is not currently playing anything."))

    @commands.command(name="queue")
    async def queue_info(self, ctx):
        queue = await self.get_queue(ctx)
        if not queue.empty():
            queue_list = "\n".join(f"**{i+1}.** {player.title}" for i, player in enumerate(list(queue._queue)))
            await ctx.send(embed=self.create_embed("Current Queue", queue_list))
        else:
            await ctx.send(embed=self.create_embed("Empty Queue", "The queue is currently empty."))

    @commands.command(name="skip")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send(embed=self.create_embed("Song Skipped", "The current song has been skipped."))

    @commands.command(name="stop")
    async def stop(self, ctx):
        queue = await self.get_queue(ctx)
        while not queue.empty():
            await queue.get()
        if ctx.voice_client:
            ctx.voice_client.stop()
        await ctx.send(embed=self.create_embed("Playback Stopped", "Music has been stopped and the queue has been cleared."))

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=self.create_embed("Error", "You are missing a required argument.", discord.Color.red()))
        elif isinstance(error, commands.NotOwner):
            await ctx.send(embed=self.create_embed("Error", "You are not the owner of this bot.", discord.Color.red()))
        else:
            await ctx.send(embed=self.create_embed("An Error Occurred", str(error), discord.Color.red()))
            raise error

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
