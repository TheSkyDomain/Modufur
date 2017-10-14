import asyncio
import datetime as dt
import mimetypes
import os
import tempfile
import traceback as tb
import webbrowser

import discord
import httplib2
import requests_oauthlib as ro
from apiclient import http
from apiclient.discovery import build
from discord.ext import commands
from oauth2client.client import flow_from_clientsecrets

#from run import config
from cogs import booru
from misc import exceptions as exc
from misc import checks
from utils import utils as u
from utils import formatter

youtube = None

tempfile.tempdir = os.getcwd()

command_dict = {}


class Utils:

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='last', aliases=['l', ','], brief='Reinvokes last command', description='Reinvokes previous command executed', hidden=True)
    async def last_command(self, ctx):
        if command_dict.get(str(ctx.message.author.id), {}).get('args', None) is not None:
            args = command_dict.get(str(ctx.message.author.id), {})['args']
        print(command_dict)

        await ctx.invoke(command_dict.get(str(ctx.message.author.id), {}).get('command', None), args)

    # [prefix]ping -> Pong!
    @commands.command(aliases=['p'], brief='Pong!', description='Returns latency from bot to Discord servers, not to user')
    @checks.del_ctx()
    async def ping(self, ctx):
        user = ctx.message.author

        await ctx.send('{}  🏓  `{}ms`'.format(round(self.bot.latency * 1000)), delete_after=5)

    @commands.command(aliases=['pre'], brief='List bot prefixes', description='Shows all used prefixes')
    @checks.del_ctx()
    async def prefix(self, ctx):
        await ctx.send('**Prefix:** `{}`'.format(u.config['prefix']))

    @commands.group(name=',send', aliases=[',s'], hidden=True)
    @commands.is_owner()
    @checks.del_ctx()
    async def send(self, ctx):
        pass

    @send.command(name='guild', aliases=['g', 'server', 's'])
    async def send_guild(self, ctx, guild, channel, *message):
        await discord.utils.get(self.bot.get_all_channels(), guild__name=guild, name=channel).send(formatter.tostring(message))

    @send.command(name='user', aliases=['u', 'member', 'm'])
    async def send_user(self, ctx, user, *message):
        await discord.utils.get(self.bot.get_all_members(), id=int(user)).send(formatter.tostring(message))

    @commands.command(aliases=['authupload', 'auth'])
    async def authenticate_upload(self, ctx):
        global youtube
        flow = flow_from_clientsecrets('client_secrets.json', scope='https://www.googleapis.com/auth/youtube.upload',
                                       login_hint='botmyned@gmail.com', redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        flow.params['access_type'] = 'offline'
        webbrowser.open_new_tab(flow.step1_get_authorize_url())
        credentials = flow.step2_exchange(input('Authorization code: '))
        youtube = build('youtube', 'v3', http=credentials.authorize(http.build_http()))
        print('Service built.')

    @commands.command(aliases=['up', 'u', 'vid', 'v'])
    @checks.is_listed()
    async def upload(self, ctx):
        global youtube
        attachments = ctx.message.attachments
        try:
            if not attachments:
                raise exc.MissingAttachment
            if len(attachments) > 1:
                raise exc.TooManyAttachments(len(attachments))
            mime = mimetypes.guess_type(attachments[0].filename)[0]
            if 'video/' in mime:
                with tempfile.NamedTemporaryFile() as temp:
                    await attachments[0].save(temp)
            else:
                raise exc.InvalidVideoFile(mime)
            print('https://www.youtube.com/watch?v={}'.format(youtube.videos().insert(part='snippet',
                                                                                      body={'categoryId': '24', 'title': 'Test'}, media_body=http.MediaFileUpload(temp.name, chunksize=-1))))
        except exc.InvalidVideoFile as e:
            await ctx.send('❌ `{}` **not valid video type.**'.format(e), delete_after=10)
        except exc.TooManyAttachments as e:
            await ctx.send('❌ `{}` **too many attachments.** Only one attachment is permitted to upload.'.format(e), delete_after=10)
        except exc.MissingAttachment:
            await ctx.send('❌ **Missing attachment.**', delete_after=10)

    @upload.error
    async def upload_error(self, ctx, error):
        pass
# http.
