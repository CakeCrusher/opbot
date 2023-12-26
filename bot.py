import discord
from discord.ext import commands, tasks
import asyncio
from eventregistry import *
import json
from dotenv import load_dotenv
import os
import json
import openai
import datetime
import wandb
from wandb.sdk.data_types.trace_tree import Trace


load_dotenv()

client = openai.OpenAI()


BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GUILD_ID = os.getenv("GUILD_ID")
ROLE_ID = os.getenv("ROLE_ID")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
WANDB_PROJECT = os.getenv("WANDB_PROJECT")

wandb.init(project=WANDB_PROJECT)


er = EventRegistry(apiKey = NEWS_API_KEY)

# get the USA URI
usUri = er.getLocationUri("USA")    # = http://en.wikipedia.org/wiki/United_States

def get_news():
    q = QueryArticlesIter(
        keywords = QueryItems.OR([
            "Artificial Intelligence",
            "LLM",
            "Generative AI",
            "NLP",
            "Prompt Engineering",
            "Machine Learning",
            "Fine-Tuning",
            "GPT"
        ]),
        minSentiment = 0.4,
        sourceLocationUri = usUri,
        dataType = ["news", "blog"]
    )
    news = []
    for art in q.execQuery(er, sortBy = "facebookShares", maxItems = 3):
        news.append(art)
        print(json.dumps(art["title"], indent = 2))

    return news


def get_summary():
    system = """You are a discord bot representing an AI expert that will produce a single report on the articles provided."""
    user_prompt = """Article bodies:
    <ARTICLE_BODIES>"""

    news = get_news()

    article_bodies = ""

    for article in news:
        article_bodies += article["body"].split(".")[0] + ". " + "\n\n\n"
        

    user_prompt = user_prompt.replace("<ARTICLE_BODIES>", article_bodies)



    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    MODEL,TEMP = "gpt-3.5-turbo", 0

    start_time_ms = datetime.datetime.now().timestamp() * 1000
    response = client.chat.completions.create(
        model=MODEL, messages=messages, temperature=TEMP, tools=[
            {
                "type": "function",
                "function": {
                    "name": "response",
                    "description": "Structured response to the user message.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "A title representative of the current state of AI according to the articles provided."
                            },
                            "report": {
                                "type": "string",
                                "description": "An informal report that recaps the articles provided in no more than 3 sentences."
                            },
                        },
                        "required": ["title", "report"]
                    }
                }
            }
        ],
        tool_choice={"type": "function", "function": {"name": "response"}}
    )
    end_time_ms = round(
        datetime.datetime.now().timestamp() * 1000
    )  # logged in milliseconds
    status = "success"
    status_message = (None,)

    pre_message = f"<@&{ROLE_ID}>\n"
    response_json = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    response_text = f"# {response_json['title']}\n{response_json['report']}"
    # add the titles linked to urls in markdown format as a list under response_text
    additional_article_info = "\n\n" + "### Articles:\n" + "\n".join(
        [f"- [{article['title']}]({article['url']})" for article in news]
    )
    # if response_text+additional_article_info is longer than 2000 characters, truncate response_text down to 1997 characters and ellipsize
    full_message = pre_message + response_text + additional_article_info
    if len(full_message) > 2000:
        overflow = len(full_message) - 2000
        response_text = response_text[:-(overflow+4)] + "..."

    full_message = pre_message + response_text + additional_article_info

    # response.usage is a pydantic class please convert to dict
    token_usage = response.usage.dict()


    root_span = Trace(
        name="root_span",
        kind="llm",  # kind can be "llm", "chain", "agent" or "tool"
        status_code=status,
        status_message=status_message,
        metadata={
            "temperature": TEMP,
            "token_usage": token_usage,
            "model_name": MODEL,
        },
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        inputs={"system_prompt": system, "query": user_prompt},
        outputs={
            "pre_message": pre_message,
            "response_text": response_text,
            "additional_article_info": additional_article_info,
            "full_message": full_message,
        },
    )

    root_span.log(name="openai_trace")

    return full_message


class MyBot(commands.Bot):
    async def setup_hook(self):
        # Create and start the background task
        self.my_background_task = self.my_background_task_loop.start()
        # get all roles
        print("\n\nGUILDS:")
        async for guild in self.fetch_guilds(limit=150):
            print(guild.name, guild.id)
            if guild.id == int(GUILD_ID):
                print("  ROLES:")
                roles = await guild.fetch_roles()
                for role in roles:
                    print("  ", role.name, role.id)

    @tasks.loop(hours=48)
    async def my_background_task_loop(self):
        # geta all channel ids
        print("\n\nCHANNELS:")
        for channel in self.get_all_channels():
            print(channel.name, channel.id)
        channel = self.get_channel(int(CHANNEL_ID))  # Replace with your channel ID
        print("\n\nChannel: ", type(channel), channel, "SENDING MESSAGE")

        message = get_summary()
        print(message)
        await channel.send(message)

    @my_background_task_loop.before_loop
    async def before_my_background_task_loop(self):
        await self.wait_until_ready()  # Wait until the bot logs in

# Initialize and run your bot
intents = discord.Intents.default()
bot = MyBot(command_prefix='/', intents=intents)

from flask import Flask, request

# Create a Flask app
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running"

# Rest of your bot code
if __name__ == "__main__":
    from threading import Thread

    # Run the Flask app on a separate thread
    Thread(target=lambda: web_app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))).start()

    # Run your Discord bot
    bot.run(BOT_TOKEN)
