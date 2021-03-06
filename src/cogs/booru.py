import asyncio
import json
import re
import sys
import traceback as tb
from contextlib import suppress
from datetime import datetime as dt
from datetime import timedelta as td
from fractions import gcd
import copy

import discord as d
from discord import errors as err
from discord.ext import commands as cmds
from discord.ext.commands import errors as errext

from cogs import tools
from misc import exceptions as exc
from misc import checks
from utils import utils as u
from utils import formatter, scraper


class MsG(cmds.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.LIMIT = 100
        self.HISTORY_LIMIT = 150
        self.reversiqueue = asyncio.Queue()
        self.heartqueue = asyncio.Queue()
        self.reversifying = False
        self.updating = False
        self.hearting = False

        time = (dt.utcnow() - td(days=29)).strftime('%d/%m/%Y/%H:%M:%S')
        self.suggested = u.setdefault('cogs/suggested.pkl', 7)
        # self.suggested = u.setdefault('cogs/suggested.pkl', {'last_update': 'test', 'tags': {}, 'total': 1})
        # print(self.suggested)
        self.favorites = u.setdefault('cogs/favorites.pkl', {})
        self.blacklists = u.setdefault('cogs/blacklists.pkl', {'global': {}, 'channel': {}, 'user': {}})

        if not self.hearting:
            self.hearting = True
            self.bot.loop.create_task(self._send_hearts())
            print('STARTED : hearting')
        if u.tasks['auto_rev']:
            for channel in u.tasks['auto_rev']:
                temp = self.bot.get_channel(channel)
                self.bot.loop.create_task(self.queue_for_reversification(temp))
                print('STARTED : auto-reversifying in #{}'.format(temp.name))
            self.reversifying = True
            self.bot.loop.create_task(self._reversify())
        if u.tasks['auto_hrt']:
            for channel in u.tasks['auto_hrt']:
                temp = self.bot.get_channel(channel)
                self.bot.loop.create_task(self.queue_for_hearts(channel=temp))
                print(f'STARTED : auto-hearting in #{temp.name}')
        # if not self.updating:
        #     self.updating = True
        #     self.bot.loop.create_task(self._update_suggested())

    def _get_icon(self, score):
        if score < 0:
            return 'https://emojipedia-us.s3.amazonaws.com/thumbs/320/twitter/103/pouting-face_1f621.png'
        elif score == 0:
            return 'https://emojipedia-us.s3.amazonaws.com/thumbs/320/mozilla/36/pile-of-poo_1f4a9.png'
        elif 10 > score > 0:
            return 'https://emojipedia-us.s3.amazonaws.com/thumbs/320/twitter/103/white-medium-star_2b50.png'
        elif 50 > score >= 10:
            return 'https://emojipedia-us.s3.amazonaws.com/thumbs/320/twitter/103/glowing-star_1f31f.png'
        elif 100 > score >= 50:
            return 'https://emojipedia-us.s3.amazonaws.com/thumbs/320/twitter/103/dizzy-symbol_1f4ab.png'
        elif score >= 100:
            return 'https://emojipedia-us.s3.amazonaws.com/thumbs/320/twitter/103/sparkles_2728.png'
        return None

    async def _update_suggested(self):
        while self.updating:
            print('Checking for tag updates...')
            print(self.suggested)

            time = dt.utcnow()
            last_update = dt.strptime(self.suggested['last_update'], '%d/%m/%Y/%H:%M:%S')
            delta = time - last_update
            print(delta.days)

            if delta.days < 30:
                print('Up to date.')
            else:
                page = 1
                pages = len(list(self.suggested['tags'].keys()))

                print(f'Last updated: {self.suggested["last_update"]}')
                print('Updating tags...')

                content = await u.fetch(f'https://e621.net/tag/index.json?order=count&limit={500}&page={page}', json=True)
                while content:
                    for tag in content:
                        self.suggested['tags'][tag['name']] = tag['count']
                        self.suggested['total'] += tag['count']
                    print(f'    UPDATED : PAGE {page} / {pages}', end='\r')

                    page += 1
                    content = await u.fetch(f'https://e621.net/tag/index.json?order=count&limit={500}&page={page}', json=True)

                u.dump(self.suggested, 'cogs/suggested.pkl')
                self.suggested['last_update'] = time.strftime('%d/%m/%Y/%H:%M:%S')

                print('\nFinished updating tags.')

            await asyncio.sleep(24 * 60 * 60)

    def _get_favorites(self, ctx, args):
        if '-f' in args or '-favs' in args or '-faves' in args or '-favorites' in args:
            if self.favorites.get(ctx.author.id, {}).get('tags', set()):
                args = ['~{}'.format(tag)
                        for tag in self.favorites[ctx.author.id]['tags']]
            else:
                raise exc.FavoritesNotFound

        return args

    async def _send_hearts(self):
        while self.hearting:
            temp = await self.heartqueue.get()

            if isinstance(temp[1], d.Embed):
                await temp[0].send(embed=temp[1])

            elif isinstance(temp[1], d.Message):
                for match in re.finditer('(https?:\/\/[^ ]*\.(?:gif|png|jpg|jpeg))', temp[1].content):
                    await temp[0].send(match)

                for attachment in temp[1].attachments:
                    await temp[0].send(attachment.url)

        print('STOPPED : hearting')

    async def queue_for_hearts(self, *, message=None, send=None, channel=None, reaction=True, timeout=60 * 60 * 24):
        def on_reaction(reaction, user):
            if reaction.emoji == '\N{HEAVY BLACK HEART}' and reaction.message.id == message.id and not user.bot:
                raise exc.Save(user)
            return False
        def on_reaction_channel(reaction, user):
            if reaction.message.channel.id == channel.id and not user.bot:
                if reaction.emoji == '\N{OCTAGONAL SIGN}' and user.permissions_in(reaction.message.channel).administrator:
                    raise exc.Abort
                if reaction.emoji == '\N{HEAVY BLACK HEART}' and (re.search('(https?:\/\/[^ ]*\.(?:gif|png|jpg|jpeg))', reaction.message.content) or reaction.message.attachments):
                    raise exc.Save(user, reaction.message)
            return False

        if message:
            try:
                if reaction:
                    await message.add_reaction('\N{HEAVY BLACK HEART}')
                    await asyncio.sleep(1)

                while self.hearting:
                    try:
                        await self.bot.wait_for('reaction_add', check=on_reaction, timeout=timeout)

                    except exc.Save as e:
                        await self.heartqueue.put((e.user, send if send else message))

            except asyncio.TimeoutError:
                await message.add_reaction('\N{WHITE HEAVY CHECK MARK}')
        else:
            try:
                while self.hearting:
                    try:
                        await self.bot.wait_for('reaction_add', check=on_reaction_channel)

                    except exc.Save as e:
                        await self.heartqueue.put((e.user, message))

            except exc.Abort:
                u.tasks['auto_hrt'].remove(channel.id)
                u.dump(u.tasks, 'cogs/tasks.pkl')
                print('STOPPED : auto-hearting in #{}'.format(channel.name))
                await channel.send('**Stopped queueing messages for hearting in** {}'.format(channel.mention))

    @cmds.command(name='autoheart', aliases=['autohrt'])
    @cmds.has_permissions(administrator=True)
    async def auto_heart(self, ctx):
        try:
            if ctx.channel.id not in u.tasks['auto_hrt']:
                u.tasks['auto_hrt'].append(ctx.channel.id)
                u.dump(u.tasks, 'cogs/tasks.pkl')
                self.bot.loop.create_task(self.queue_for_hearts(channel=ctx.channel))
                print('STARTED : auto-hearting in #{}'.format(ctx.channel.name))
                await ctx.send('**Auto-hearting all messages in {}**'.format(ctx.channel.mention))
            else:
                raise exc.Exists

        except exc.Exists:
            message = await ctx.send('**Already auto-hearting in {}.** React with \N{OCTAGONAL SIGN} to stop.'.format(ctx.channel.mention))
            await message.add_reaction('\N{OCTAGONAL SIGN}')

    # @cmds.command()
    # async def auto_post(self, ctx):
    #     try:
    #         if ctx.channel.id not in u.tasks['auto_post']:
    #             u.tasks['auto_post'].append(ctx.channel.id)
    #             u.dump(u.tasks, 'cogs/tasks.pkl')
    #             self.bot.loop.create_task(self.queue_for_posting(ctx.channel))
    #             if not self.posting:
    #                 self.bot.loop.create_task(self._post())
    #                 self.posting = True
    #
    #             print('STARTED : auto-posting in #{}'.format(ctx.channel.name))
    #             await ctx.send('**Auto-posting all images in {}**'.format(ctx.channel.mention))
    #         else:
    #             raise exc.Exists
    #
    #     except exc.Exists:
    #         await ctx.send('**Already auto-posting in {}.** Type `stop` to stop.'.format(ctx.channel.mention))
    #         await u.add_reaction(ctx.message, '\N{CROSS MARK}')

    @cmds.group(aliases=['tag', 't'], brief='(G) Get info on tags', description='Group command for obtaining info on tags\n\nUsage:\n\{p\}tag \{flag\} \{tag(s)\}')
    async def tags(self, ctx):
        pass

    # Tag search
    @tags.command(name='related', aliases=['relate', 'rel', 'r'], brief='(tags) Search for related tags', description='Return related tags for given tag(s)\n\nExample:\n\{p\}tag related wolf')
    async def _tags_related(self, ctx, *args):
        kwargs = u.get_kwargs(ctx, args)
        tags = kwargs['remaining']
        related = []
        c = 0

        await ctx.trigger_typing()

        for tag in tags:
            tag_request = await u.fetch(f'https://e621.net/tag/related.json?tags={tag}', json=True)
            for rel in tag_request.get(tag, []):
                related.append(rel[0])

            if related:
                await ctx.send('`{}` **related tags:**\n```\n{}```'.format(tag, ' '.join(related)))
            else:
                await ctx.send(f'**No related tags found for:** `{tag}`')

            related.clear()
            c += 1

        if not c:
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')

    # Tag aliases
    @tags.command(name='aliases', aliases=['alias', 'als', 'a'], brief='(tags) Search for tag aliases', description='Return aliases for given tag(s)\n\nExample:\n\{p\}tag alias wolf')
    async def _tags_aliases(self, ctx, *args):
        kwargs = u.get_kwargs(ctx, args)
        tags = kwargs['remaining']
        aliases = []
        c = 0

        await ctx.trigger_typing()

        for tag in tags:
            alias_request = await u.fetch(f'https://e621.net/tag_alias/index.json?aliased_to={tag}&approved=true', json=True)
            for dic in alias_request:
                aliases.append(dic['name'])

            if aliases:
                await ctx.send('`{}` **aliases:**\n```\n{}```'.format(tag, ' '.join(aliases)))
            else:
                await ctx.send(f'**No aliases found for:** `{tag}`')

            aliases.clear()
            c += 1

        if not c:
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')

    @cmds.group(aliases=['g'], brief='(G) Get e621 elements', description='Group command for obtaining various elements like post info\n\nUsage:\n\{p\}get \{flag\} \{args\}')
    async def get(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send('**Use a flag to get items.**\n*Type* `{}help get` *for more info.*'.format(ctx.prefix))
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    @get.command(name='info', aliases=['i'], brief='(get) Get info from post', description='Return info for given post URL or ID\n\nExample:\n\{p\}get info 1145042')
    async def _get_info(self, ctx, *args):
        try:
            kwargs = u.get_kwargs(ctx, args)
            posts = kwargs['remaining']

            if not posts:
                raise exc.MissingArgument

            for ident in posts:
                await ctx.trigger_typing()

                ident = ident if not ident.isdigit() else re.search(
                    'show/([0-9]+)', ident).group(1)
                post = await u.fetch(f'https://e621.net/posts/{ident}.json', json=True)
                post = post['post']

                embed = d.Embed(
                    title=', '.join(post['tags']['artist']), url=f'https://e621.net/posts/{post["id"]}', color=ctx.me.color if isinstance(ctx.channel, d.TextChannel) else u.color)
                embed.set_thumbnail(url=post['file']['url'])
                embed.set_author(name=f'{post["file"]["width"]} x {post["file"]["height"]}',
                                 url=f'https://e621.net/posts?tags=ratio:{post["file"]["width"]/post["file"]["height"]:.2f}', icon_url=ctx.author.avatar_url)
                embed.set_footer(text=post['score']['total'],
                                 icon_url=self._get_icon(post['score']['total']))

        except exc.MissingArgument:
            await ctx.send('\N{HEAVY EXCLAMATION MARK SYMBOL} **Invalid url**')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    @get.command(name='image', aliases=['img'], brief='(get) Get direct image from post', description='Return direct image URL for given post\n\nExample:\n\{p\}get image 1145042')
    async def _get_image(self, ctx, *args):
        try:
            kwargs = u.get_kwargs(ctx, args)
            urls = kwargs['remaining']
            c = 0

            if not urls:
                raise exc.MissingArgument

            for url in urls:
                await ctx.trigger_typing()

                await ctx.send(await scraper.get_image(url))

                c += 1

                # except
                    # await ctx.send(f'**No aliases found for:** `{tag}`')

            if not c:
                await u.add_reaction(ctx.message, '\N{CROSS MARK}')

        except exc.MissingArgument:
            await ctx.send('\N{HEAVY EXCLAMATION MARK SYMBOL} **Invalid url or file**')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    @get.command(name='pool', aliases=['p'], brief='(get) Get pool from query', description='Return pool info for given query\n\nExample:\n\{p\}get pool 1145042')
    async def _get_pool(self, ctx, *args):
        def on_reaction(reaction, user):
            if reaction.emoji == '\N{OCTAGONAL SIGN}' and reaction.message.id == ctx.message.id and user.id is ctx.author.id:
                raise exc.Abort(match)
            return False

        def on_message(msg):
            return msg.content.isdigit() and int(msg.content) <= len(pools) and int(msg.content) > 0 and msg.author.id is ctx.author.id and msg.channel.id is ctx.channel.id

        try:
            kwargs = u.get_kwargs(ctx, args)
            query = kwargs['remaining']
            ident = None

            await ctx.trigger_typing()

            pools = []
            pool_request = await u.fetch(f'https://e621.net/pools.json?search[name_matches]={" ".join(query)}', json=True)
            if len(pool_request) > 1:
                for pool in pool_request:
                    pools.append(pool['name'])
                match = await ctx.send('**Multiple pools found for `{}`.** Type the number of the correct match\n```\n{}```'.format(' '.join(query), '\n'.join(['{} {}'.format(c, elem) for c, elem in enumerate(pools, 1)])))

                await u.add_reaction(ctx.message, '\N{OCTAGONAL SIGN}')
                done, pending = await asyncio.wait([self.bot.wait_for('reaction_add', check=on_reaction, timeout=60),
                                                    self.bot.wait_for('reaction_remove', check=on_reaction, timeout=60), self.bot.wait_for('message', check=on_message, timeout=60)], return_when=asyncio.FIRST_COMPLETED)
                for future in done:
                    selection = future.result()

                with suppress(err.Forbidden):
                    await match.delete()
                tempool = [pool for pool in pool_request if pool['name']
                           == pools[int(selection.content) - 1]][0]
                with suppress(err.Forbidden):
                    await selection.delete()
            elif pool_request:
                tempool = pool_request[0]
            else:
                raise exc.NotFound

            await ctx.send(f'**{tempool["name"]}**\nhttps://e621.net/pools/{tempool["id"]}')

        except exc.Abort as e:
            await e.message.edit(content='\N{NO ENTRY SIGN}')

    # Reverse image searches a linked image using the public iqdb
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    @cmds.command(name='reverse', aliases=['rev', 'ris'], brief='Reverse image search from Kheina and SauceNAO', description='NSFW\nReverse-search an image with given URL')
    async def reverse(self, ctx, *args):
        try:
            kwargs = u.get_kwargs(ctx, args)
            urls, remove = kwargs['remaining'], kwargs['remove']
            c = 0

            if not urls and not ctx.message.attachments:
                raise exc.MissingArgument

            for attachment in ctx.message.attachments:
                urls.append(attachment.url)

            async with ctx.channel.typing():
                for url in urls:
                    try:
                        result = await scraper.get_post(url)

                        embed = d.Embed(
                            title=result['artist'],
                            url=result['source'],
                            color=ctx.me.color if isinstance(ctx.channel, d.TextChannel) else u.color)
                        embed.set_image(url=result['thumbnail'])
                        embed.set_author(name=result['similarity'] + '% Match', icon_url=ctx.author.avatar_url)
                        embed.set_footer(text=result['database'])

                        await ctx.send(embed=embed)

                        c += 1

                    except exc.MatchError as e:
                        await ctx.send('**No probable match for:** `{}`'.format(e))

            if not c:
                await u.add_reaction(ctx.message, '\N{CROSS MARK}')
            elif remove:
                with suppress(err.NotFound):
                    await ctx.message.delete()

        except exc.MissingArgument:
            await ctx.send(
                '\N{HEAVY EXCLAMATION MARK SYMBOL} **Invalid url or file.**\n'
                'Be sure the link directs to an image file')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.SizeError as e:
            await ctx.send(f'`{e}` **too large.**\nMaximum is 8 MB')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except err.HTTPException:
            await ctx.send(
                '\N{HEAVY EXCLAMATION MARK SYMBOL} **Search engines returned an unexpected result.**\n'
                'They may be offline')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.ImageError:
            await ctx.send(
                '\N{HEAVY EXCLAMATION MARK SYMBOL} **Search engines were denied access to this file.**\n'
                'Try opening it in a browser and uploading the file to Discord')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    @cmds.command(name='reversify', aliases=['revify', 'risify', 'rify'])
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    async def reversify(self, ctx, *args):
        try:
            dest = ctx
            kwargs = u.get_kwargs(ctx, args, limit=5)
            remove, limit = kwargs['remove'], kwargs['limit']
            links = {}
            c = 0

            if not ctx.author.permissions_in(ctx.channel).manage_messages:
                dest = ctx.author

            async for message in ctx.channel.history(limit=self.HISTORY_LIMIT * limit):
                if c >= limit:
                    break
                if message.author.id != self.bot.user.id and (re.search('(https?:\/\/[^ ]*\.(?:gif|png|jpg|jpeg))', message.content) is not None or message.embeds or message.attachments):
                    links[message] = []
                    for match in re.finditer('(https?:\/\/[^ ]*\.(?:gif|png|jpg|jpeg))', message.content):
                        links[message].append(match.group(0))
                    for embed in message.embeds:
                        if embed.image.url is not d.Embed.Empty:
                            links[message].append(embed.image.url)
                    for attachment in message.attachments:
                        links[message].append(attachment.url)

                    await message.add_reaction('\N{HOURGLASS WITH FLOWING SAND}')
                    c += 1

            if not links:
                raise exc.NotFound

            n = 1
            async with ctx.channel.typing():
                for message, urls in links.items():
                    for url in urls:
                        try:
                            result = await scraper.get_post(url)

                            embed = d.Embed(
                                title=result['artist'],
                                url=result['source'],
                                color=ctx.me.color if isinstance(ctx.channel, d.TextChannel) else u.color)
                            embed.set_image(url=result['thumbnail'])
                            embed.set_author(name=result['similarity'] + '% Match', icon_url=ctx.author.avatar_url)
                            embed.set_footer(text=result['database'])

                            await dest.send(embed=embed)
                            await message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

                            if remove:
                                with suppress(err.NotFound):
                                    await message.delete()

                        except exc.MatchError as e:
                            await dest.send('`{} / {}` **No probable match for:** `{}`'.format(n, len(links), e))
                            await message.add_reaction('\N{CROSS MARK}')
                            c -= 1
                        except exc.SizeError as e:
                            await dest.send(f'`{e}` **too large.**\nMaximum is 8 MB')
                            await message.add_reaction('\N{CROSS MARK}')
                            c -= 1

                        finally:
                            n += 1

            if c <= 0:
                await u.add_reaction(ctx.message, '\N{CROSS MARK}')

        except exc.NotFound:
            await dest.send('**No matches found**')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.BoundsError as e:
            await dest.send('`{}` **invalid limit.**\nQuery limited to 5'.format(e))
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except err.HTTPException:
            await dest.send(
                '\N{HEAVY EXCLAMATION MARK SYMBOL} **Search engines returned an unexpected result.**\n'
                'They may be offline')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.ImageError:
            await ctx.send(
                '\N{HEAVY EXCLAMATION MARK SYMBOL} **Search engines were denied access to this file.**\n'
                'Try opening it in a browser and uploading the file to Discord')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    async def _reversify(self):
        while self.reversifying:
            message = await self.reversiqueue.get()
            urls = []

            for match in re.finditer('(https?:\/\/[^ ]*\.(?:gif|png|jpg|jpeg))', message.content):
                urls.append(match.group(0))
            for embed in message.embeds:
                if embed.image.url is not d.Embed.Empty:
                    urls.append(embed.image.url)
            for attachment in message.attachments:
                urls.append(attachment.url)

            async with message.channel.typing():
                for url in urls:
                    try:
                        result = await scraper.get_post(url)

                        embed = d.Embed(
                            title=result['artist'],
                            url=result['source'],
                            color=message.me.color if isinstance(message.channel, d.TextChannel) else u.color)
                        embed.set_image(url=result['thumbnail'])
                        embed.set_author(name=result['similarity'] + '% Match', icon_url=message.author.avatar_url)
                        embed.set_footer(text=result['database'])

                        await message.channel.send(embed=embed)

                        await message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

                        with suppress(err.NotFound):
                            await message.delete()

                    except exc.MatchError as e:
                        await message.channel.send('**No probable match for:** `{}`'.format(e))
                        await message.add_reaction('\N{CROSS MARK}')
                    except exc.SizeError as e:
                        await message.channel.send(f'`{e}` **too large.** Maximum is 8 MB')
                        await message.add_reaction('\N{HEAVY EXCLAMATION MARK SYMBOL}')
                    except Exception:
                        await message.channel.send(f'**An unknown error occurred.**')
                        await message.add_reaction('\N{WARNING SIGN}')

        print('STOPPED : reversifying')

    async def queue_for_reversification(self, channel):
        def check(msg):
            if 'stop r' in msg.content.lower() and msg.channel is channel and msg.author.guild_permissions.administrator:
                raise exc.Abort
            elif msg.channel is channel and msg.author.id != self.bot.user.id and (re.search('(https?:\/\/[^ ]*\.(?:gif|png|jpg|jpeg))', msg.content) is not None or msg.attachments or msg.embeds):
                return True
            return False

        try:
            while self.reversifying:
                message = await self.bot.wait_for('message', check=check)
                await self.reversiqueue.put(message)
                await message.add_reaction('\N{HOURGLASS WITH FLOWING SAND}')

        except exc.Abort:
            u.tasks['auto_rev'].remove(channel.id)
            u.dump(u.tasks, 'cogs/tasks.pkl')
            if not u.tasks['auto_rev']:
                self.reversifying = False
            print('STOPPED : reversifying #{}'.format(channel.name))
            await channel.send('**Stopped queueing messages for reversification in** {}'.format(channel.mention))

    @cmds.command(name='autoreversify', aliases=['autorev'])
    @cmds.has_permissions(manage_channels=True)
    async def auto_reversify(self, ctx):
        if ctx.channel.id not in u.tasks['auto_rev']:
            u.tasks['auto_rev'].append(ctx.channel.id)
            u.dump(u.tasks, 'cogs/tasks.pkl')
            self.bot.loop.create_task(
                self.queue_for_reversification(ctx.channel))
            if not self.reversifying:
                self.bot.loop.create_task(self._reversify())
                self.reversifying = True

            print('STARTED : auto-reversifying in #{}'.format(ctx.channel.name))
            await ctx.send('**Auto-reversifying all images in** {}'.format(ctx.channel.mention))
        else:
            await ctx.send('**Already auto-reversifying in {}.** Type `stop r(eversifying)` to stop.'.format(ctx.channel.mention))
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')

    async def _get_pool(self, ctx, *, booru='e621', query=[]):
        def on_reaction(reaction, user):
            if reaction.emoji == '\N{OCTAGONAL SIGN}' and reaction.message.id == ctx.message.id and user.id is ctx.author.id:
                raise exc.Abort(match)
            return False

        def on_message(msg):
            return msg.content.isdigit() and int(msg.content) <= len(pools) and int(msg.content) > 0 and msg.author.id is ctx.author.id and msg.channel.id is ctx.channel.id

        posts = {}
        pool = {}

        try:
            pools = []
            pool_request = await u.fetch(f'https://{booru}.net/pools.json?search[name_matches]={" ".join(query)}', json=True)
            if len(pool_request) > 1:
                for pool in pool_request:
                    pools.append(pool['name'])
                match = await ctx.send('**Multiple pools found for `{}`.** Type the number of the correct match.\n```\n{}```'.format(' '.join(query), '\n'.join(['{} {}'.format(c, elem) for c, elem in enumerate(pools, 1)])))

                await u.add_reaction(ctx.message, '\N{OCTAGONAL SIGN}')
                done, pending = await asyncio.wait([self.bot.wait_for('reaction_add', check=on_reaction, timeout=60),
                                                    self.bot.wait_for('reaction_remove', check=on_reaction, timeout=60),
                                                    self.bot.wait_for('message', check=on_message, timeout=60)],
                                                    return_when=asyncio.FIRST_COMPLETED)
                for future in done:
                    selection = future.result()

                with suppress(err.Forbidden):
                    await match.delete()
                tempool = [pool for pool in pool_request if pool['name']
                           == pools[int(selection.content) - 1]][0]
                with suppress(err.Forbidden):
                    await selection.delete()
                pool = {'name': tempool['name'], 'id': tempool['id']}

                await ctx.trigger_typing()
            elif pool_request:
                tempool = pool_request[0]
                pool = {'name': pool_request[0]
                        ['name'], 'id': pool_request[0]['id']}
            else:
                raise exc.NotFound

            for ident in tempool['post_ids']:
                post = await u.fetch(f'https://{booru}.net/posts/{ident}.json', json=True)
                post = post['post']
                posts[post['id']] = {'artist': ', '.join(
                    post['tags']['artist']), 'file_url': post['file']['url'], 'score': post['score']['total']}

                await asyncio.sleep(0.5)

            return pool, posts

        except exc.Abort as e:
            await e.message.delete()
            raise exc.Continue

    # Messy code that checks image limit and tags in blacklists
    async def _get_posts(self, ctx, *, booru='e621', tags=[], limit=1, previous={}):
        blacklist = set()
        # Creates temp blacklist based on context
        for lst in ('blacklist', 'aliases'):
            default = set() if lst == 'blacklist' else {}

            for bl in (self.blacklists['global'].get(lst, default),
                       self.blacklists['channel'].get(ctx.channel.id, {}).get(lst, default),
                       self.blacklists['user'].get(ctx.author.id, {}).get(lst, default)):
                if lst == 'aliases':
                    temp = list(bl.keys()) + [tag for tags in bl.values() for tag in tags]
                    temp = set(temp)
                else:
                    temp = bl

                blacklist.update(temp)
        # Checks for, assigns, and removes first order in tags if possible
        order = [tag for tag in tags if 'order:' in tag]
        if order:
            order = order[0]
            tags.remove(order)
        else:
            order = 'order:random'
        # Checks if tags are in local blacklists
        if tags:
            if (len(tags) > 40):
                raise exc.TagBoundsError(' '.join(tags[40:]))
            for tag in tags:
                if tag == 'swf' or tag == 'webm' or tag in blacklist:
                    raise exc.TagBlacklisted(tag)

        # Checks for blacklisted tags in endpoint blacklists - try/except is for continuing the parent loop
        posts = {}
        temposts = len(posts)
        empty = 0
        c = 0
        while len(posts) < limit:
            if c == limit * 5 + (self.LIMIT / 5):
                raise exc.Timeout

            request = await u.fetch(f'https://{booru}.net/posts.json?tags={"+".join([order] + tags)}&limit={int(320)}', json=True)
            if len(request['posts']) == 0:
                raise exc.NotFound(' '.join(tags))
            if len(request['posts']) < limit:
                limit = len(request['posts'])

            for post in request['posts']:
                if 'swf' in post['file']['ext'] or 'webm' in post['file']['ext']:
                    continue
                try:
                    post_tags = [tag for tags in post['tags'].values() for tag in tags]
                    for tag in blacklist:
                        if tag in post_tags:
                            raise exc.Continue
                except exc.Continue:
                    continue
                if post['id'] not in posts.keys() and post['id'] not in previous.keys():
                    posts[post['id']] = {'artist': ', '.join(
                        post['tags']['artist']), 'file_url': post['file']['url'], 'score': post['score']['total']}
                if len(posts) == limit:
                    break

            if len(posts) == temposts:
                empty += 1
                if empty == 5:
                    break
            else:
                empty = 0
                temposts = len(posts)
                c += 1

        if posts:
            return posts, order
        else:
            raise exc.NotFound(' '.join(tags))

    # Creates reaction-based paginator for linked pools
    @cmds.command(name='poolpage', aliases=['poolp', 'pp', 'e621pp', 'e6pp', '6pp'], brief='e621 pool paginator', description='e621 | NSFW\nShow pools in a page format')
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    async def pool_paginator(self, ctx, *args):
        def on_reaction(reaction, user):
            if reaction.emoji == '\N{OCTAGONAL SIGN}' and reaction.message.id == ctx.message.id and (user.id is ctx.author.id or user.permissions_in(reaction.message.channel).manage_messages):
                raise exc.Abort
            elif reaction.emoji == '\N{HEAVY BLACK HEART}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.Save
            elif reaction.emoji == '\N{LEFTWARDS BLACK ARROW}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.Left
            elif reaction.emoji == '\N{NUMBER SIGN}\N{COMBINING ENCLOSING KEYCAP}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.GoTo
            elif reaction.emoji == '\N{BLACK RIGHTWARDS ARROW}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.Right
            return False

        def on_message(msg):
            return msg.content.isdigit() and 0 <= int(msg.content) <= len(posts) and msg.author.id is ctx.author.id and msg.channel.id is ctx.channel.id

        try:
            kwargs = u.get_kwargs(ctx, args)
            query = kwargs['remaining']
            hearted = {}
            c = 1

            if not args:
                raise exc.MissingArgument

            async with ctx.channel.typing():
                pool, posts = await self._get_pool(ctx, booru='e621', query=query)
                keys = list(posts.keys())
                values = list(posts.values())

                embed = d.Embed(
                    title=values[c - 1]['artist'], url='https://e621.net/posts/{}'.format(keys[c - 1]), color=ctx.me.color if isinstance(ctx.channel, d.TextChannel) else u.color)
                embed.set_image(url=values[c - 1]['file_url'])
                embed.set_author(name=pool['name'],
                                 url='https://e621.net/pools/{}'.format(pool['id']), icon_url=ctx.author.avatar_url)
                embed.set_footer(text='{} / {}'.format(c, len(posts)),
                                 icon_url=self._get_icon(values[c - 1]['score']))

                paginator = await ctx.send(embed=embed)

                for emoji in ('\N{HEAVY BLACK HEART}', '\N{LEFTWARDS BLACK ARROW}', '\N{NUMBER SIGN}\N{COMBINING ENCLOSING KEYCAP}', '\N{BLACK RIGHTWARDS ARROW}'):
                    await paginator.add_reaction(emoji)
                await u.add_reaction(ctx.message, '\N{OCTAGONAL SIGN}')
                await asyncio.sleep(1)

            while not self.bot.is_closed():
                try:
                    await asyncio.gather(*[self.bot.wait_for('reaction_add', check=on_reaction, timeout=8*60),
                                           self.bot.wait_for('reaction_remove', check=on_reaction, timeout=8*60)])

                except exc.Save:
                    if keys[c - 1] not in hearted:
                        hearted[keys[c - 1]] = copy.deepcopy(embed)

                        await paginator.edit(content='\N{HEAVY BLACK HEART}')
                    else:
                        del hearted[keys[c - 1]]

                        await paginator.edit(content='\N{BROKEN HEART}')

                except exc.Left:
                    if c > 1:
                        c -= 1
                        embed.title = values[c - 1]['artist']
                        embed.url = 'https://e621.net/posts/{}'.format(
                            keys[c - 1])
                        embed.set_footer(text='{} / {}'.format(c, len(posts)),
                                         icon_url=self._get_icon(values[c - 1]['score']))
                        embed.set_image(url=values[c - 1]['file_url'])

                        await paginator.edit(content='\N{HEAVY BLACK HEART}' if keys[c - 1] in hearted.keys() else None, embed=embed)
                    else:
                        await paginator.edit(content='\N{BLACK RIGHTWARDS ARROW}')

                except exc.GoTo:
                    await paginator.edit(content='\N{INPUT SYMBOL FOR NUMBERS}')
                    number = await self.bot.wait_for('message', check=on_message, timeout=8*60)

                    if int(number.content) != 0:
                        c = int(number.content)

                        embed.title = values[c - 1]['artist']
                        embed.url = 'https://e621.net/posts/{}'.format(
                            keys[c - 1])
                        embed.set_footer(text='{} / {}'.format(c, len(posts)),
                                         icon_url=self._get_icon(values[c - 1]['score']))
                        embed.set_image(url=values[c - 1]['file_url'])

                    if ctx.channel is d.TextChannel:
                        with suppress(errext.CheckFailure):
                            await number.delete()

                    await paginator.edit(content='\N{HEAVY BLACK HEART}' if keys[c - 1] in hearted.keys() else None, embed=embed)

                except exc.Right:
                    if c < len(keys):
                        c += 1
                        embed.title = values[c - 1]['artist']
                        embed.url = 'https://e621.net/posts/{}'.format(
                            keys[c - 1])
                        embed.set_footer(text='{} / {}'.format(c, len(posts)),
                                         icon_url=self._get_icon(values[c - 1]['score']))
                        embed.set_image(url=values[c - 1]['file_url'])

                        await paginator.edit(content='\N{HEAVY BLACK HEART}' if keys[c - 1] in hearted.keys() else None, embed=embed)
                    else:
                        await paginator.edit(content='\N{LEFTWARDS BLACK ARROW}')

        except exc.Abort:
            try:
                await paginator.edit(content='\N{WHITE HEAVY CHECK MARK}')
            except UnboundLocalError:
                await ctx.send('\N{WHITE HEAVY CHECK MARK}')
        except asyncio.TimeoutError:
            try:
                await paginator.edit(content='\N{HOURGLASS}')
            except UnboundLocalError:
                await ctx.send('\N{HOURGLASS}')
        except exc.MissingArgument:
            await ctx.send('**Missing argument**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.NotFound:
            await ctx.send('**Pool not found**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.Timeout:
            await ctx.send('**Request timed out**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.Continue:
            pass

        finally:
            if hearted:
                await u.add_reaction(ctx.message, '\N{HOURGLASS WITH FLOWING SAND}')

                n = 1
                for embed in hearted.values():
                    await ctx.author.send(content=f'`{n} / {len(hearted)}`', embed=embed)
                    n += 1

    async def _get_paginator(self, ctx, args, booru='e621'):
        def on_reaction(reaction, user):
            if reaction.emoji == '\N{OCTAGONAL SIGN}' and reaction.message.id == ctx.message.id and (user.id is ctx.author.id or user.permissions_in(reaction.message.channel).manage_messages):
                raise exc.Abort
            elif reaction.emoji == '\N{HEAVY BLACK HEART}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.Save
            elif reaction.emoji == '\N{LEFTWARDS BLACK ARROW}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.Left
            elif reaction.emoji == '\N{BLACK RIGHTWARDS ARROW}' and reaction.message.id == paginator.id and user.id is ctx.author.id:
                raise exc.Right
            return False

        def on_message(msg):
            return msg.content.isdigit() and 0 <= int(msg.content) <= len(posts) and msg.author.id is ctx.author.id and msg.channel.id is ctx.channel.id

        try:
            kwargs = u.get_kwargs(ctx, args)
            tags = kwargs['remaining']
            limit = self.LIMIT / 5
            hearted = {}
            c = 1

            tags = self._get_favorites(ctx, tags)

            await ctx.trigger_typing()

            posts, order = await self._get_posts(ctx, booru=booru, tags=tags, limit=limit)
            keys = list(posts.keys())
            values = list(posts.values())

            embed = d.Embed(
                title=values[c - 1]['artist'], url='https://{}.net/posts/{}'.format(booru, keys[c - 1]), color=ctx.me.color if isinstance(ctx.channel, d.TextChannel) else u.color)
            embed.set_image(url=values[c - 1]['file_url'])
            embed.set_author(name=' '.join(tags) if tags else order,
                             url='https://{}.net/posts?tags={}'.format(booru, '+'.join(tags) if tags else order), icon_url=ctx.author.avatar_url)
            embed.set_footer(text=values[c - 1]['score'],
                             icon_url=self._get_icon(values[c - 1]['score']))

            paginator = await ctx.send(embed=embed)

            for emoji in ('\N{HEAVY BLACK HEART}', '\N{LEFTWARDS BLACK ARROW}', '\N{BLACK RIGHTWARDS ARROW}'):
                await paginator.add_reaction(emoji)
            await u.add_reaction(ctx.message, '\N{OCTAGONAL SIGN}')
            await asyncio.sleep(1)

            while not self.bot.is_closed():
                try:
                    await asyncio.gather(*[self.bot.wait_for('reaction_add', check=on_reaction, timeout=8*60),
                                           self.bot.wait_for('reaction_remove', check=on_reaction, timeout=8*60)])

                except exc.Save:
                    if keys[c - 1] not in hearted.keys():
                        hearted[keys[c - 1]] = copy.deepcopy(embed)

                        await paginator.edit(content='\N{HEAVY BLACK HEART}')
                    else:
                        del hearted[keys[c - 1]]

                        await paginator.edit(content='\N{BROKEN HEART}')

                except exc.Left:
                    if c > 1:
                        c -= 1
                        embed.title = values[c - 1]['artist']
                        embed.url = 'https://{}.net/posts/{}'.format(
                            booru,
                            keys[c - 1])
                        embed.set_footer(text=values[c - 1]['score'],
                                         icon_url=self._get_icon(values[c - 1]['score']))
                        embed.set_image(url=values[c - 1]['file_url'])

                        await paginator.edit(content='\N{HEAVY BLACK HEART}' if keys[c - 1] in hearted.keys() else None, embed=embed)
                    else:
                        await paginator.edit(content='\N{BLACK RIGHTWARDS ARROW}')

                except exc.Right:
                    try:
                        if c % limit == 0:
                            await ctx.trigger_typing()
                            temposts, order = await self._get_posts(ctx, booru=booru, tags=tags, limit=limit, previous=posts)
                            posts.update(temposts)

                            keys = list(posts.keys())
                            values = list(posts.values())

                        if c < len(keys):
                            c += 1
                            embed.title = values[c - 1]['artist']
                            embed.url = 'https://{}.net/posts/{}'.format(
                                booru,
                                keys[c - 1])
                            embed.set_footer(text=values[c - 1]['score'],
                                             icon_url=self._get_icon(values[c - 1]['score']))
                            embed.set_image(url=values[c - 1]['file_url'])

                            await paginator.edit(content='\N{HEAVY BLACK HEART}' if keys[c - 1] in hearted.keys() else None, embed=embed)
                        else:
                            await paginator.edit(content='\N{LEFTWARDS BLACK ARROW}')

                    except exc.NotFound:
                        await paginator.edit(content='\N{LEFTWARDS BLACK ARROW}')

        except exc.Abort:
            try:
                await paginator.edit(content='\N{WHITE HEAVY CHECK MARK}')
            except UnboundLocalError:
                await ctx.send('\N{HOURGLASS}')
        except asyncio.TimeoutError:
            try:
                await paginator.edit(content='\N{HOURGLASS}')
            except UnboundLocalError:
                await ctx.send('\N{HOURGLASS}')
        except exc.NotFound as e:
            await ctx.send('`{}` **not found**'.format(e))
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.TagBlacklisted as e:
            await ctx.send('\N{NO ENTRY SIGN} `{}` **blacklisted**'.format(e))
            await u.add_reaction(ctx.message, '\N{NO ENTRY SIGN}')
        except exc.TagBoundsError as e:
            await ctx.send('`{}` **out of bounds.** Tags limited to 40.'.format(e))
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.FavoritesNotFound:
            await ctx.send('**You have no favorite tags**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.Timeout:
            await ctx.send('**Request timed out**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')

        finally:
            if hearted:
                await u.add_reaction(ctx.message, '\N{HOURGLASS WITH FLOWING SAND}')

                n = 1
                for embed in hearted.values():
                    await ctx.author.send(content=f'`{n} / {len(hearted)}`', embed=embed)
                    n += 1

    @cmds.command(name='e621page', aliases=['e621p', 'e6p', '6p'])
    @checks.is_nsfw()
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    async def e621_paginator(self, ctx, *args):
        await self._get_paginator(ctx, args, booru='e621')


    @cmds.command(name='e926page', aliases=['e926p', 'e9p', '9p'])
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    async def e926_paginator(self, ctx, *args):
        await self._get_paginator(ctx, args, booru='e926')

    async def _get_images(self, ctx, args, booru='e621'):
        try:
            kwargs = u.get_kwargs(ctx, args, limit=3)
            args, limit = kwargs['remaining'], kwargs['limit']

            tags = self._get_favorites(ctx, args)

            await ctx.trigger_typing()

            posts, order = await self._get_posts(ctx, booru=booru, tags=tags, limit=limit)

            for ident, post in posts.items():
                embed = d.Embed(title=post['artist'], url='https://{}.net/posts/{}'.format(booru, ident),
                                color=ctx.me.color if isinstance(ctx.channel, d.TextChannel) else u.color)
                embed.set_image(url=post['file_url'])
                embed.set_author(name=' '.join(tags) if tags else order,
                                 url='https://{}.net/posts?tags={}'.format(booru, '+'.join(tags) if tags else order), icon_url=ctx.author.avatar_url)
                embed.set_footer(
                    text=post['score'], icon_url=self._get_icon(post['score']))

                message = await ctx.send(embed=embed)

                self.bot.loop.create_task(self.queue_for_hearts(message=message, send=embed))

        except exc.TagBlacklisted as e:
            await ctx.send('`{}` **blacklisted**'.format(e))
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.BoundsError as e:
            await ctx.send('`{}` **out of bounds.** Images limited to 3.'.format(e))
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.TagBoundsError as e:
            await ctx.send('`{}` **out of bounds.** Tags limited to 40.'.format(e))
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        except exc.NotFound as e:
            await ctx.send('`{}` **not found**'.format(e))
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.FavoritesNotFound:
            await ctx.send('**You have no favorite tags**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')
        except exc.Timeout:
            await ctx.send('**Request timed out**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')

    # Searches for and returns images from e621.net given tags when not blacklisted
    @cmds.command(aliases=['e6', '6'], brief='e621 | NSFW', description='e621 | NSFW\nTag-based search for e621.net\n\nYou can only search 5 tags and 6 images at once for now.\ne6 [tags...] ([# of images])')
    @checks.is_nsfw()
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    async def e621(self, ctx, *args):
        await self._get_images(ctx, args, booru='e621')

    # Searches for and returns images from e926.net given tags when not blacklisted
    @cmds.command(aliases=['e9', '9'], brief='e926 | SFW', description='e926 | SFW\nTag-based search for e926.net\n\nYou can only search 5 tags and 6 images at once for now.\ne9 [tags...] ([# of images])')
    @cmds.cooldown(1, 5, cmds.BucketType.member)
    async def e926(self, ctx, *args):
        await self._get_images(ctx, args, booru='e926')

    # @cmds.group(aliases=['fave', 'fav', 'f'])
    # async def favorite(self, ctx):
    #     if not ctx.invoked_subcommand:
    #         await ctx.send('**Use a flag to manage favorites.**\n*Type* `{}help fav` *for more info.*'.format(ctx.prefix))
    #         await u.add_reaction(ctx.message, '\N{CROSS MARK}')
    #
    # @favorite.error
    # async def favorite_error(self, ctx, error):
    #     pass
    #
    # @favorite.group(name='get', aliases=['g'])
    # async def _get_favorite(self, ctx):
    #     pass
    #
    # @_get_favorite.command(name='tags', aliases=['t'])
    # async def __get_favorite_tags(self, ctx, *args):
    #     await ctx.send('\N{WHITE MEDIUM STAR} {}**\'s favorite tags:**\n```\n{}```'.format(ctx.author.mention, ' '.join(self.favorites.get(ctx.author.id, {}).get('tags', set()))))
    #
    # @_get_favorite.command(name='posts', aliases=['p'])
    # async def __get_favorite_posts(self, ctx):
    #     pass
    #
    # @favorite.group(name='add', aliases=['a'])
    # async def _add_favorite(self, ctx):
    #     pass
    #
    # @_add_favorite.command(name='tags', aliases=['t'])
    # async def __add_favorite_tags(self, ctx, *args):
    #     try:
    #         kwargs = u.get_kwargs(ctx, args)
    #         tags = kwargs['remaining']
    #
    #         for tag in tags:
    #             if tag in self.blacklists['user']['blacklist'].get(ctx.author.id, set()):
    #                 raise exc.TagBlacklisted(tag)
    #         with suppress(KeyError):
    #             if len(self.favorites[ctx.author.id]['tags']) + len(tags) > 5:
    #                 raise exc.BoundsError
    #
    #         self.favorites.setdefault(ctx.author.id, {}).setdefault(
    #             'tags', set()).update(tags)
    #         u.dump(self.favorites, 'cogs/favorites.pkl')
    #
    #         await ctx.send('{} **added to their favorites:**\n```\n{}```'.format(ctx.author.mention, ' '.join(tags)))
    #
    #     except exc.BoundsError:
    #         await ctx.send('**Favorites list currently limited to:** `5`')
    #         await u.add_reaction(ctx.message, '\N{CROSS MARK}')
    #     except exc.TagBlacklisted as e:
    #         await ctx.send('\N{NO ENTRY SIGN} `{}` **blacklisted**')
    #         await u.add_reaction(ctx.message, '\N{NO ENTRY SIGN}')
    #
    # @_add_favorite.command(name='posts', aliases=['p'])
    # async def __add_favorite_posts(self, ctx, *posts):
    #     pass
    #
    # @favorite.group(name='remove', aliases=['r'])
    # async def _remove_favorite(self, ctx):
    #     pass
    #
    # @_remove_favorite.command(name='tags', aliases=['t'])
    # async def __remove_favorite_tags(self, ctx, *args):
    #     try:
    #         kwargs = u.get_kwargs(ctx, args)
    #         tags = kwargs['remaining']
    #
    #         for tag in tags:
    #             try:
    #                 self.favorites[ctx.author.id].get(
    #                     'tags', set()).remove(tag)
    #
    #             except KeyError:
    #                 raise exc.TagError(tag)
    #
    #         u.dump(self.favorites, 'cogs/favorites.pkl')
    #
    #         await ctx.send('{} **removed from their favorites:**\n```\n{}```'.format(ctx.author.mention, ' '.join(tags)))
    #
    #     except KeyError:
    #         await ctx.send('**You do not have any favorites**')
    #         await u.add_reaction(ctx.message, '\N{CROSS MARK}')
    #     except exc.TagError as e:
    #         await ctx.send('`{}` **not in favorites**'.format(e))
    #         await u.add_reaction(ctx.message, '\N{CROSS MARK}')
    #
    # @_remove_favorite.command(name='posts', aliases=['p'])
    # async def __remove_favorite_posts(self, ctx):
    #     pass
    #
    # @favorite.group(name='clear', aliases=['c'])
    # async def _clear_favorite(self, ctx):
    #     pass
    #
    # @_clear_favorite.command(name='tags', aliases=['t'])
    # async def __clear_favorite_tags(self, ctx, *args):
    #     with suppress(KeyError):
    #         del self.favorites[ctx.author.id]
    #         u.dump(self.favorites, 'cogs/favorites.pkl')
    #
    #     await ctx.send('{}**\'s favorites cleared**'.format(ctx.author.mention))
    #
    # @_clear_favorite.command(name='posts', aliases=['p'])
    # async def __clear_favorite_posts(self, ctx):
    #     pass

    @cmds.group(
        aliases=['bl', 'b'],
        brief='(G) Manage blacklists',
        description='Manage global, guild (WIP), channel, and personal blacklists',
        usage='[option] [blacklist] [--aliases|-a] [tags...]')
    async def blacklist(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send(
                '**Use a flag to manage blacklists.**\n'
                f'*Type* `{ctx.prefix}help bl` *for more info.*')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')
        elif not ctx.args:
            await ctx.send('\N{HEAVY EXCLAMATION MARK SYMBOL} **Missing arguments**')

    @blacklist.group(
        name='get',
        aliases=['g'],
        brief='Get a blacklist',
        description='Get global, channel, or personal blacklists',
        usage='[blacklist]')
    async def get_blacklist(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send('\N{HEAVY EXCLAMATION MARK SYMBOL} **Invalid blacklist**')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    @get_blacklist.command(
        name='global',
        aliases=['gl', 'g'],
        brief='Get global blacklist',
        description='Get global blacklist\n\n'
                    'In accordance with Discord\'s ToS: cub, related tags, and their aliases are blacklisted')
    async def get_global_blacklist(self, ctx, *args):
        args, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}
        blacklist = self.blacklists['global'].get(lst, default)

        if blacklist:
            await formatter.paginate(
                ctx,
                blacklist,
                start=f'\N{NO ENTRY SIGN} **Global {lst}:**')
        else:
            await ctx.send(f'\N{CROSS MARK} **No global {lst} found**')

    @get_blacklist.command(
        name='channel',
        aliases=['chan', 'ch', 'c'],
        brief='Get channel blacklist',
        description='Get channel blacklist')
    async def get_channel_blacklist(self, ctx, *args):
        args, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}
        blacklist = self.blacklists['channel'].get(ctx.channel.id, {}).get(lst, default)

        if blacklist:
            await formatter.paginate(
                ctx,
                blacklist,
                start=f'\N{NO ENTRY SIGN} {ctx.channel.mention} **{lst}:**')
        else:
            await ctx.send(f'\N{CROSS MARK} **No {lst} found for {ctx.channel.mention}**')

    @get_blacklist.command(
        name='me',
        aliases=['m'],
        brief='Get your personal blacklist',
        description='Get your personal blacklist')
    async def get_user_blacklist(self, ctx, *args):
        args, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}
        blacklist = self.blacklists['user'].get(ctx.author.id, {}).get(lst, default)

        if blacklist:
            await formatter.paginate(
                ctx,
                blacklist,
                start=f'\N{NO ENTRY SIGN} {ctx.author.mention}**\'s {lst}:**')
        else:
            await ctx.send(f'\N{CROSS MARK} **No {lst} found for {ctx.author.mention}**')

    @blacklist.group(
        name='add',
        aliases=['a'],
        brief='Add tags to a blacklist',
        description='Add tags to global, channel, or personal blacklists',
        usage='[blacklist] [tags...]')
    async def add_tags(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send('\N{CROSS MARK} **Invalid blacklist**')
            await u.add_reaction(ctx.message, '\N{CROSS MARK}')

    async def _add(self, tags, lst, alias=False):
        if not alias:
            if tags:
                lst.update(tags)
                u.dump(self.blacklists, 'cogs/blacklists.pkl')

            return tags
        else:
            aliases = {}

            if tags:
                for tag in tags:
                    request = await u.fetch(
                        f'https://e621.net/tag_alias/index.json?aliased_to={tag}&approved=true',
                        json=True)

                    for elem in request:
                        if elem['name']:
                            aliases.setdefault(tag, set()).add(elem['name'])

                if aliases:
                    lst.update(aliases)
                    u.dump(self.blacklists, 'cogs/blacklists.pkl')

            return list(aliases.keys())

    @add_tags.command(
        name='global',
        aliases=['gl', 'g'],
        brief='Add tags to global blacklist',
        description='Add tags to global blacklist',
        usage='[tags...]')
    @cmds.is_owner()
    async def add_global_tags(self, ctx, *args):
        tags, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}

        async with ctx.channel.typing():
            added = await self._add(
                tags,
                self.blacklists['global'].setdefault(lst, default),
                alias=True if lst == 'aliases' else False)

        await formatter.paginate(
            ctx,
            added,
            start=f'\N{WHITE HEAVY CHECK MARK} **Added to global {lst}:**')

    @add_tags.command(
        name='channel',
        aliases=['chan', 'ch', 'c'],
        brief='Add tags to channel blacklist',
        description='Add tags to channel blacklist',
        usage='[tags...]')
    @cmds.has_permissions(manage_channels=True)
    async def add_channel_tags(self, ctx, *args):
        tags, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}

        async with ctx.channel.typing():
            added = await self._add(
                tags,
                self.blacklists['channel'].setdefault(ctx.channel.id, {}).setdefault(lst, default),
                alias=True if lst == 'aliases' else False)

        await formatter.paginate(
            ctx,
            added,
            start=f'\N{WHITE HEAVY CHECK MARK} **Added to {ctx.channel.mention} {lst}:**')

    @add_tags.command(
        name='me',
        aliases=['m'],
        brief='Add tags to personal blacklist',
        description='Add tags to personal blacklist',
        usage='[tags...]')
    async def add_user_tags(self, ctx, *args):
        tags, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}

        async with ctx.channel.typing():
            added = await self._add(
                tags,
                self.blacklists['user'].setdefault(ctx.author.id, {}).setdefault(lst, default),
                alias=True if lst == 'aliases' else False)

        await formatter.paginate(
            ctx,
            added,
            start=f'\N{WHITE HEAVY CHECK MARK} **Added to {ctx.author.mention}\'s {lst}:**')

    @blacklist.group(
        name='remove',
        aliases=['rm', 'r'],
        brief='Remove tags from a blacklist',
        description='Remove tags from global, channel, or personal blacklists',
        usage='[blacklist] [tags...]')
    async def remove_tags(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send('\N{HEAVY EXCLAMATION MARK SYMBOL} **Invalid blacklist**')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    def _remove(self, remove, lst):
        removed = set()

        if remove:
            if type(lst) is set:
                for tag in remove:
                    with suppress(KeyError):
                        lst.remove(tag)
                        removed.add(tag)
            else:
                temp = copy.deepcopy(lst)
                for k in temp.keys():
                    if k in remove:
                        with suppress(KeyError):
                            del lst[k]
                            removed.add(k)
                    else:
                        lst[k] = set([tag for tag in lst[k] if tag not in remove])
                lst = temp
                removed.update([tag for k, v in lst.items() for tag in v if tag in remove])

            u.dump(self.blacklists, 'cogs/blacklists.pkl')

        return removed

    @remove_tags.command(
        name='global',
        aliases=['gl', 'g'],
        brief='Remove tags from global blacklist',
        description='Remove tags from global blacklist',
        usage='[tags...]')
    @cmds.is_owner()
    async def remove_global_tags(self, ctx, *args):
        tags, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}

        async with ctx.channel.typing():
            removed = self._remove(
                tags,
                self.blacklists['global'].get(lst, default))

        await formatter.paginate(
            ctx,
            removed,
            start=f'\N{WHITE HEAVY CHECK MARK} **Removed from global {lst}:**')

    @remove_tags.command(
        name='channel',
        aliases=['ch', 'c'],
        brief='Remove tags from channel blacklist',
        description='Remove tags from channel blacklist',
        usage='[tags...]')
    @cmds.has_permissions(manage_channels=True)
    async def remove_channel_tags(self, ctx, *args):
        tags, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}

        async with ctx.channel.typing():
            removed = self._remove(
                tags,
                self.blacklists['channel'].get(ctx.channel.id, {}).get(lst, default))

        await formatter.paginate(
            ctx,
            removed,
            start=f'\N{WHITE HEAVY CHECK MARK} **Removed from {ctx.channel.mention} {lst}:**')

    @remove_tags.command(
        name='me',
        aliases=['m'],
        brief='Remove tags from personal blacklist',
        description='Remove tags from personal blacklist',
        usage='[tags...]')
    async def remove_user_tags(self, ctx, *args):
        tags, lst = u.kwargs(args)
        default = set() if lst == 'blacklist' else {}

        async with ctx.channel.typing():
            removed = self._remove(
                tags,
                self.blacklists['user'].get(ctx.author.id, {}).get(lst, default))

        await formatter.paginate(
            ctx,
            removed,
            start=f'\N{WHITE HEAVY CHECK MARK} **Removed from {ctx.author.mention}\'s {lst}:**')

    @blacklist.group(
        name='clear',
        aliases=['cl', 'c'],
        brief='Delete a blacklist',
        description='Delete global, channel, or personal blacklists',
        usage='[blacklist]')
    async def clear_blacklist(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send('\N{HEAVY EXCLAMATION MARK SYMBOL} **Invalid blacklist**')
            await u.add_reaction(ctx.message, '\N{HEAVY EXCLAMATION MARK SYMBOL}')

    @clear_blacklist.command(
        name='global',
        aliases=['gl', 'g'],
        brief='Delete global blacklist',
        description='Delete global blacklist')
    @cmds.is_owner()
    async def clear_global_blacklist(self, ctx, *args):
        args, lst = u.kwargs(args)

        async with ctx.channel.typing():
            with suppress(KeyError):
                del self.blacklists['global'][lst]

            u.dump(self.blacklists, 'cogs/blacklists.pkl')

        await ctx.send(f'\N{WHITE HEAVY CHECK MARK} **Global {lst} cleared**')

    @clear_blacklist.command(
        name='channel',
        aliases=['ch', 'c'],
        brief='Delete channel blacklist',
        description='Delete channel blacklist')
    @cmds.has_permissions(manage_channels=True)
    async def clear_channel_blacklist(self, ctx, *args):
        args, lst = u.kwargs(args)

        async with ctx.channel.typing():
            with suppress(KeyError):
                del self.blacklists['channel'][ctx.channel.id][lst]

            u.dump(self.blacklists, 'cogs/blacklists.pkl')

        await ctx.send(f'\N{WHITE HEAVY CHECK MARK} **{ctx.channel.mention} {lst} cleared**')

    @clear_blacklist.command(
        name='me',
        aliases=['m'],
        brief='Delete your personal blacklist',
        description='Delete your personal blacklist')
    async def clear_user_blacklist(self, ctx, *args):
        args, lst = u.kwargs(args)

        async with ctx.channel.typing():
            with suppress(KeyError):
                del self.blacklists['user'][ctx.author.id][lst]

            u.dump(self.blacklists, 'cogs/blacklists.pkl')

        await ctx.send(f'\N{WHITE HEAVY CHECK MARK} **{ctx.author.mention}\'s {lst} cleared**')
