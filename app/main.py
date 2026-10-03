import asyncio
import os
import base64
import tempfile
import threading
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from openai import OpenAI
from faster_whisper import WhisperModel
from supabase import create_client, Client

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")


# ============================================================
# AI CLIENT
# ============================================================

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# One reliable free multimodal model for both text + images
AI_MODEL = "qwen/qwen3.8-27b:free"


# ============================================================
# SUPABASE CLIENT
# ============================================================

supabase: Client | None = None

if SUPABASE_URL and SUPABASE_SECRET_KEY:
    try:
        supabase = create_client(
            SUPABASE_URL,
            SUPABASE_SECRET_KEY,
        )
        print("Supabase client initialized.")
    except Exception as e:
        print(f"Supabase initialization error: {e}")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Crop Advisor",
    description=(
        "AI agricultural assistant using Telegram, "
        "Whisper, OpenRouter, Open-Meteo and Supabase."
    ),
    version="1.0.0",
)


# ============================================================
# WHISPER
# ============================================================

whisper_model = None
whisper_lock = threading.Lock()


def get_whisper_model():

    global whisper_model

    with whisper_lock:

        if whisper_model is None:

            print("Loading Whisper model...")

            whisper_model = WhisperModel(
                "tiny",
                device="cpu",
                compute_type="int8",
            )

            print("Whisper model loaded.")

    return whisper_model


# ============================================================
# SUPABASE — FARMER
# ============================================================

def save_farmer(
    telegram_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    crop: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
):

    if supabase is None:
        print("ERROR: Supabase client is not configured.")
        return None

    try:

        # ----------------------------------------------------
        # Check whether farmer already exists
        # ----------------------------------------------------

        existing = (
            supabase
            .table("farmers")
            .select("id")
            .eq(
                "telegram_user_id",
                telegram_user_id,
            )
            .execute()
        )

        data = {
            "telegram_user_id": telegram_user_id,
            "username": username,
            "first_name": first_name,
        }

        if crop is not None:
            data["crop"] = crop

        if latitude is not None:
            data["latitude"] = latitude

        if longitude is not None:
            data["longitude"] = longitude

        # ----------------------------------------------------
        # UPDATE EXISTING FARMER
        # ----------------------------------------------------

        if existing.data:

            farmer_id = existing.data[0]["id"]

            (
                supabase
                .table("farmers")
                .update(data)
                .eq("id", farmer_id)
                .execute()
            )

            print(
                f"Farmer updated successfully: {farmer_id}"
            )

            return farmer_id

        # ----------------------------------------------------
        # INSERT NEW FARMER
        # ----------------------------------------------------

        response = (
            supabase
            .table("farmers")
            .insert(data)
            .execute()
        )

        if response.data:

            farmer_id = response.data[0]["id"]

            print(
                f"New farmer saved successfully: {farmer_id}"
            )

            return farmer_id

        print("Farmer insert returned no data.")

    except Exception as e:

        print(
            f"SUPABASE FARMER ERROR: {repr(e)}"
        )

    return None


# ============================================================
# SUPABASE — INTERACTION
# ============================================================

def save_interaction(
    farmer_id: str | None,
    interaction_type: str,
    user_message: str,
    ai_response: str,
):

    if supabase is None:

        print(
            "ERROR: Supabase client is not configured."
        )

        return

    if farmer_id is None:

        print(
            "ERROR: No farmer ID. "
            "Interaction cannot be saved."
        )

        return

    try:

        response = (
            supabase
            .table("interactions")
            .insert(
                {
                    "farmer_id": farmer_id,
                    "interaction_type": interaction_type,
                    "user_message": user_message,
                    "ai_response": ai_response,
                }
            )
            .execute()
        )

        if response.data:

            print(
                "Interaction saved successfully."
            )

        else:

            print(
                "Interaction insert returned no data."
            )

    except Exception as e:

        print(
            f"SUPABASE INTERACTION ERROR: {repr(e)}"
        )


# ============================================================
# SUPABASE - LOAD PROFILE
# ============================================================

def get_farmer(telegram_user_id: int) -> dict | None:

    if supabase is None:
        return None

    try:

        response = (
            supabase
            .table("farmers")
            .select("id, crop, latitude, longitude")
            .eq("telegram_user_id", telegram_user_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

    except Exception as e:

        print(f"SUPABASE GET FARMER ERROR: {repr(e)}")

    return None


# ============================================================
# WEATHER
# ============================================================

async def get_weather(
    latitude: float,
    longitude: float,
) -> str:

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": (
            "temperature_2m_max,"
            "temperature_2m_min,"
            "precipitation_sum,"
            "weather_code"
        ),
        "timezone": "auto",
        "forecast_days": 7,
    }

    try:

        async with httpx.AsyncClient(
            timeout=15
        ) as http:

            response = await http.get(
                url,
                params=params,
            )

            response.raise_for_status()

            data = response.json()

        daily = data["daily"]

        weather_lines = []

        for i in range(7):

            date = daily["time"][i]

            max_temp = daily[
                "temperature_2m_max"
            ][i]

            min_temp = daily[
                "temperature_2m_min"
            ][i]

            rain = daily[
                "precipitation_sum"
            ][i]

            weather_lines.append(
                f"{date}: "
                f"{min_temp}°C–{max_temp}°C, "
                f"rain {rain} mm"
            )

        return "\n".join(weather_lines)

    except Exception as e:

        print(
            f"Weather error: {e}"
        )

        return (
            "Weather information is currently unavailable."
        )


# ============================================================
# AI FARM ADVICE
# ============================================================

def generate_advice(
    crop: str,
    question: str,
    weather: str,
) -> str:

    prompt = f"""
You are Crop Advisor, a practical agricultural assistant.

The farmer grows:
{crop}

The farmer asks:
{question}

Local 7-day weather forecast:
{weather}

Give practical, concise advice that a farmer can actually use.

Use the weather information when relevant.

Do not give a definite disease diagnosis.
If the question involves a possible disease or pest,
describe it as a possibility and explain what the farmer
should check.

If a photo would help, recommend sending one.

Do not discuss AI safety classifications.
Do not output phrases such as "User Safety: safe".
Answer the farmer's actual agricultural question.

Use this structure:

Advice:
- Give the main practical recommendation.

Weather consideration:
- Explain whether the upcoming weather matters.

Next step:
- Give one or two specific actions.

Keep the answer under 180 words.
"""

    try:

        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Crop Advisor, an agricultural "
                        "assistant. Always answer the user's "
                        "actual agricultural question."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        answer = response.choices[0].message.content

        if not answer:

            return (
                "I couldn't generate advice right now. "
                "Please try again."
            )

        return answer.strip()

    except Exception as e:

        print(
            f"AI advice error: {repr(e)}"
        )

        return (
            "Sorry, I couldn't generate advice right now. "
            "Please try again."
        )


# ============================================================
# CROP PHOTO ANALYSIS
# ============================================================

def analyze_crop_image(
    crop: str,
    image_bytes: bytes,
) -> str:

    image_data = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    image_url = (
        f"data:image/jpeg;base64,{image_data}"
    )

    prompt = f"""
Analyze this actual agricultural crop photograph.

Crop:
{crop}

Carefully inspect the actual image for:

- leaf discoloration
- yellowing
- spots
- curling
- wilting
- holes
- insects
- mold or fungal-like patterns
- physical damage
- unusual growth
- nutrient-deficiency-like symptoms

Actually analyze what is visible.

Do NOT return a generic safety response.

Do NOT say "User Safety: safe".

Do not give a definite disease diagnosis.
Describe possible causes based only on visible evidence.

If the image is unclear, say so.

Keep the response under 180 words.

Use:

OBSERVATION:
What is visibly happening.

POSSIBLE CAUSES:
Possible explanations.

NEXT STEPS:
What the farmer should check or do.

WHEN TO GET HELP:
When professional agricultural help may be useful.
"""

    try:

        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an agricultural crop-image "
                        "analysis assistant. Analyze the actual "
                        "image and provide useful observations."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                },
            ],
        )

        answer = response.choices[0].message.content

        if not answer:

            return (
                "I couldn't analyze the image. "
                "Please try sending the photo again."
            )

        return answer.strip()

    except Exception as e:

        print(
            f"Image analysis error: {repr(e)}"
        )

        return (
            "I couldn't analyze the crop image right now. "
            "Please try sending the photo again."
        )


# ============================================================
# TRANSCRIPTION
# ============================================================

def transcribe_audio(
    audio_bytes: bytes,
) -> str:

    model = get_whisper_model()

    with tempfile.NamedTemporaryFile(
        suffix=".ogg",
        delete=False,
    ) as temp_file:

        temp_file.write(audio_bytes)

        temp_path = temp_file.name

    try:

        segments, info = model.transcribe(
            temp_path,
            beam_size=5,
        )

        transcription = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

        print(
            f"Transcription: {transcription}"
        )

        return transcription

    finally:

        try:
            os.remove(temp_path)

        except OSError:
            pass


# ============================================================
# FASTAPI ENDPOINTS
# ============================================================

@app.get("/")
async def root():

    return {
        "message": "Crop Advisor API is running",
        "status": "online",
    }


@app.get("/weather")
async def weather(
    latitude: float,
    longitude: float,
):

    forecast = await get_weather(
        latitude,
        longitude,
    )

    return {
        "latitude": latitude,
        "longitude": longitude,
        "forecast": forecast,
    }


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
):

    audio_bytes = await file.read()

    transcription = await asyncio.to_thread(
            transcribe_audio,
        audio_bytes
    )

    return {
        "transcription": transcription,
    }


@app.post("/ask")
async def ask(
    crop: str,
    question: str,
    latitude: float,
    longitude: float,
):

    forecast = await get_weather(
        latitude,
        longitude,
    )

    advice = await asyncio.to_thread(
            generate_advice,
        crop,
        question,
        forecast,
    )

    return {
        "crop": crop,
        "question": question,
        "weather": forecast,
        "advice": advice,
    }


# ============================================================
# TELEGRAM BOT
# ============================================================

telegram_app = None


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if user is None:
        return

    farmer_id = await asyncio.to_thread(
            save_farmer,
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    context.user_data[
        "farmer_id"
    ] = farmer_id

    context.user_data[
        "waiting_for_crop"
    ] = True

    context.user_data[
        "waiting_for_location"
    ] = False

    await update.message.reply_text(
        "🌱 Welcome to Crop Advisor!\n\n"
        "I can help you with crop questions, "
        "weather-based advice, and crop photo analysis.\n\n"
        "First, what crop are you growing?"
    )


# ============================================================
# TEXT
# ============================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    user = update.effective_user

    if user is None:
        return

    await ensure_profile(user.id, context)

    message = update.message.text.strip()

    # --------------------------------------------------------
    # CROP SETUP
    # --------------------------------------------------------

    if context.user_data.get(
        "waiting_for_crop"
    ):

        crop = message

        farmer_id = await asyncio.to_thread(
            save_farmer,
            telegram_user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            crop=crop,
        )

        context.user_data[
            "farmer_id"
        ] = farmer_id

        context.user_data[
            "crop"
        ] = crop

        context.user_data[
            "waiting_for_crop"
        ] = False

        context.user_data[
            "waiting_for_location"
        ] = True

        await update.message.reply_text(
            f"Great — I'll help you with {crop}.\n\n"
            "Now please share your farm location using "
            "Telegram's location button so I can use your "
            "local 7-day weather forecast.",
            reply_markup=LOCATION_KEYBOARD,
        )

        return

    # --------------------------------------------------------
    # NORMAL QUESTION
    # --------------------------------------------------------

    crop = context.user_data.get(
        "crop",
        "the farmer's crop",
    )

    latitude = context.user_data.get(
        "latitude"
    )

    longitude = context.user_data.get(
        "longitude"
    )

    if (
        latitude is not None
        and longitude is not None
    ):

        weather = await get_weather(
            latitude,
            longitude,
        )

    else:

        weather = (
            "No farm location has been provided yet. "
            "Give general agricultural advice without "
            "weather-specific recommendations."
        )

    await update.message.reply_text(
        "🌱 Thinking..."
    )

    advice = await asyncio.to_thread(
            generate_advice,
        crop,
        message,
        weather,
    )

    farmer_id = context.user_data.get(
        "farmer_id"
    )

    if farmer_id is None:

        farmer_id = await asyncio.to_thread(
            save_farmer,
            telegram_user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            crop=crop,
            latitude=latitude,
            longitude=longitude,
        )

        context.user_data[
            "farmer_id"
        ] = farmer_id

    await asyncio.to_thread(
            save_interaction,
        farmer_id=farmer_id,
        interaction_type="text",
        user_message=message,
        ai_response=advice,
    )

    await update.message.reply_text(
        advice
    )


# ============================================================
# LOCATION
# ============================================================

async def handle_location(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    user = update.effective_user

    if user is None:
        return

    location = update.message.location

    latitude = location.latitude
    longitude = location.longitude

    context.user_data[
        "latitude"
    ] = latitude

    context.user_data[
        "longitude"
    ] = longitude

    crop = context.user_data.get(
        "crop"
    )

    farmer_id = await asyncio.to_thread(
            save_farmer,
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        crop=crop,
        latitude=latitude,
        longitude=longitude,
    )

    context.user_data[
        "farmer_id"
    ] = farmer_id

    context.user_data[
        "waiting_for_location"
    ] = False

    await update.message.reply_text(
        "📍 Location saved!\n\n"
        "You can now:\n"
        "• Ask me a crop question\n"
        "• Send me a voice question 🎤\n"
        "• Send me a crop photo 📷\n\n"
        "I'll use your local weather when giving advice.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ============================================================
# VOICE
# ============================================================

async def handle_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    user = update.effective_user

    if user is None:
        return

    await ensure_profile(user.id, context)

    crop = context.user_data.get(
        "crop",
        "the farmer's crop",
    )

    await update.message.reply_text(
        "🎤 I received your voice message. "
        "Transcribing..."
    )

    try:

        voice = update.message.voice

        telegram_file = (
            await context.bot.get_file(
                voice.file_id
            )
        )

        audio_bytes = (
            await telegram_file.download_as_bytearray()
        )

        transcription = await asyncio.to_thread(
            transcribe_audio,
            bytes(audio_bytes)
        )

        if not transcription:

            await update.message.reply_text(
                "I couldn't understand the voice message. "
                "Please try again."
            )

            return

        latitude = context.user_data.get(
            "latitude"
        )

        longitude = context.user_data.get(
            "longitude"
        )

        if (
            latitude is not None
            and longitude is not None
        ):

            weather = await get_weather(
                latitude,
                longitude,
            )

        else:

            weather = (
                "No farm location has been provided yet."
            )

        await update.message.reply_text(
            f"📝 I heard:\n{transcription}\n\n"
            "🌱 Generating advice..."
        )

        advice = await asyncio.to_thread(
            generate_advice,
            crop,
            transcription,
            weather,
        )

        farmer_id = context.user_data.get(
            "farmer_id"
        )

        if farmer_id is None:

            farmer_id = await asyncio.to_thread(
            save_farmer,
                telegram_user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                crop=crop,
                latitude=latitude,
                longitude=longitude,
            )

            context.user_data[
                "farmer_id"
            ] = farmer_id

        await asyncio.to_thread(
            save_interaction,
            farmer_id=farmer_id,
            interaction_type="voice",
            user_message=transcription,
            ai_response=advice,
        )

        await update.message.reply_text(
            advice
        )

    except Exception as e:

        print(
            f"Voice handler error: {repr(e)}"
        )

        await update.message.reply_text(
            "Sorry, something went wrong while "
            "processing your voice message."
        )


# ============================================================
# PHOTO
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    user = update.effective_user

    if user is None:
        return

    await ensure_profile(user.id, context)

    crop = context.user_data.get(
        "crop",
        "unknown crop",
    )

    await update.message.reply_text(
        "📷 I'm analyzing the crop photo..."
    )

    try:

        photo = update.message.photo[-1]

        telegram_file = (
            await context.bot.get_file(
                photo.file_id
            )
        )

        image_bytes = (
            await telegram_file.download_as_bytearray()
        )

        analysis = await asyncio.to_thread(
            analyze_crop_image,
            crop,
            bytes(image_bytes),
        )

        farmer_id = context.user_data.get(
            "farmer_id"
        )

        if farmer_id is None:

            farmer_id = await asyncio.to_thread(
            save_farmer,
                telegram_user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                crop=crop,
                latitude=context.user_data.get(
                    "latitude"
                ),
                longitude=context.user_data.get(
                    "longitude"
                ),
            )

            context.user_data[
                "farmer_id"
            ] = farmer_id

        await asyncio.to_thread(
            save_interaction,
            farmer_id=farmer_id,
            interaction_type="photo",
            user_message=(
                f"Crop photo analysis for {crop}"
            ),
            ai_response=analysis,
        )

        await update.message.reply_text(
            analysis
        )

    except Exception as e:

        print(
            f"Photo handler error: {repr(e)}"
        )

        await update.message.reply_text(
            "Sorry, I couldn't analyze that photo. "
            "Please try sending it again."
        )


# ============================================================
# PROFILE + COMMANDS
# ============================================================

LOCATION_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📍 Share my farm location", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

BOT_COMMANDS = [
    ("start", "Set up your farm profile"),
    ("help", "What I can do"),
    ("profile", "See your saved crop and location"),
    ("weather", "7-day forecast for your farm"),
    ("setcrop", "Change your crop"),
    ("setlocation", "Update your farm location"),
]


async def ensure_profile(
    telegram_user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Reload crop/location from Supabase after a server restart."""

    if context.user_data.get("farmer_id"):
        return

    farmer = await asyncio.to_thread(
        get_farmer,
        telegram_user_id,
    )

    if not farmer:
        return

    context.user_data["farmer_id"] = farmer["id"]

    if farmer.get("crop"):
        context.user_data["crop"] = farmer["crop"]

    if farmer.get("latitude") is not None:
        context.user_data["latitude"] = farmer["latitude"]

    if farmer.get("longitude") is not None:
        context.user_data["longitude"] = farmer["longitude"]


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    await update.message.reply_text(
        "🌱 Crop Advisor: your agronomist in your pocket\n\n"
        "Ask me anything about your crop:\n"
        "• Type a question\n"
        "• Send a voice message 🎤\n"
        "• Send a photo of a leaf or plant 📷\n\n"
        "Commands:\n"
        "/profile: your saved crop and location\n"
        "/weather: 7-day forecast for your farm\n"
        "/setcrop: change your crop\n"
        "/setlocation: update your farm location\n\n"
        "I give practical guidance, not a diagnosis. For serious "
        "crop losses, also talk to a local agricultural extension officer."
    )


async def profile_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if update.message is None or user is None:
        return

    await ensure_profile(user.id, context)

    crop = context.user_data.get("crop")
    lat = context.user_data.get("latitude")
    lon = context.user_data.get("longitude")

    if lat is not None and lon is not None:
        location = f"✅ saved ({lat:.2f}, {lon:.2f})"
    else:
        location = "❌ not set (use /setlocation)"

    await update.message.reply_text(
        "👤 Your farm profile\n\n"
        f"Crop: {crop or '❌ not set (use /setcrop)'}\n"
        f"Location: {location}"
    )


async def weather_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if update.message is None or user is None:
        return

    await ensure_profile(user.id, context)

    lat = context.user_data.get("latitude")
    lon = context.user_data.get("longitude")

    if lat is None or lon is None:

        await update.message.reply_text(
            "I don't have your farm location yet. "
            "Tap the button to share it.",
            reply_markup=LOCATION_KEYBOARD,
        )

        return

    forecast = await get_weather(lat, lon)

    await update.message.reply_text(
        "🌦 7-day forecast for your farm:\n\n" + forecast
    )


async def setcrop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    context.user_data["waiting_for_crop"] = True

    await update.message.reply_text(
        "Which crop are you growing now?"
    )


async def setlocation_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    context.user_data["waiting_for_location"] = True

    await update.message.reply_text(
        "Tap the button below to share your farm location.",
        reply_markup=LOCATION_KEYBOARD,
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    print(f"Telegram error: {repr(context.error)}")

    if isinstance(update, Update) and update.effective_message:

        try:

            await update.effective_message.reply_text(
                "Sorry, something went wrong on my side. "
                "Please try again in a moment."
            )

        except Exception:
            pass


# ============================================================
# TELEGRAM APPLICATION
# ============================================================

def create_telegram_application():

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    for command, handler in (
        ("help", help_command),
        ("profile", profile_command),
        ("weather", weather_command),
        ("setcrop", setcrop_command),
        ("setlocation", setlocation_command),
    ):
        application.add_handler(
            CommandHandler(command, handler)
        )

    application.add_error_handler(error_handler)

    application.add_handler(
        MessageHandler(
            filters.LOCATION,
            handle_location,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.VOICE,
            handle_voice,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    return application


# ============================================================
# FASTAPI LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(
    fastapi_app: FastAPI,
):

    global telegram_app

    print("Starting Crop Advisor...")

    if not OPENROUTER_API_KEY:
        print(
            "WARNING: OPENROUTER_API_KEY is missing."
        )

    if not TELEGRAM_BOT_TOKEN:
        print(
            "WARNING: TELEGRAM_BOT_TOKEN is missing."
        )

    if not SUPABASE_URL:
        print(
            "WARNING: SUPABASE_URL is missing."
        )

    if not SUPABASE_SECRET_KEY:
        print(
            "WARNING: SUPABASE_SECRET_KEY is missing."
        )

    telegram_app = create_telegram_application()

    await telegram_app.initialize()

    await telegram_app.bot.set_my_commands(BOT_COMMANDS)

    await telegram_app.start()

    await telegram_app.updater.start_polling()

    print("Telegram bot is running.")
    print("Crop Advisor API is running.")

    yield

    print("Stopping Crop Advisor...")

    if telegram_app.updater:
        await telegram_app.updater.stop()

    await telegram_app.stop()

    await telegram_app.shutdown()

    print("Crop Advisor stopped.")


# ============================================================
# ATTACH LIFESPAN
# ============================================================

app.router.lifespan_context = lifespan