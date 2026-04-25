"""
EDITH Weather Module — Open-Meteo (Free, No API key, High Privacy)

Uses Open-Meteo for weather data and ipinfo.io for location detection.
No API keys required. No tracking. Fully private.
"""

import requests
import datetime
from config import get_logger
from errors import Result

log = get_logger("weather")

# WMO Weather interpretation codes → human descriptions
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

# WMO codes → emoji
WMO_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌧️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    66: "🌧️", 67: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "❄️",
    77: "❄️", 80: "🌦️", 81: "🌧️",
    82: "⛈️", 85: "🌨️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def _detect_location() -> dict:
    """Get user's location. Uses .env override or defaults to Fatehpur, UP."""
    import os
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    city = os.getenv("EDITH_CITY", "Fatehpur")
    lat = float(os.getenv("EDITH_LAT", "25.93"))
    lon = float(os.getenv("EDITH_LON", "80.81"))

    return {
        "city": city,
        "region": "Uttar Pradesh",
        "country": "IN",
        "lat": lat,
        "lon": lon,
    }


def get_current_weather() -> Result:
    """Get current weather using Open-Meteo (free, no API key needed). Returns Result[dict]."""
    try:
        location = _detect_location()
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location["lat"],
                "longitude": location["lon"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data["current"]

        weather_code = current.get("weather_code", 0)
        return Result.success({
            "city": location["city"],
            "region": location["region"],
            "temp": current["temperature_2m"],
            "feels_like": current["apparent_temperature"],
            "humidity": current["relative_humidity_2m"],
            "wind_speed": current["wind_speed_10m"],
            "description": WMO_CODES.get(weather_code, "Unknown"),
            "emoji": WMO_EMOJI.get(weather_code, "🌡️"),
            "weather_code": weather_code,
        })
    except Exception as e:
        log.error(f"Weather fetch failed: {e}")
        return Result.from_exception(e)


def format_weather(weather: dict) -> str:
    """Format weather data into a human-readable string."""
    if not weather:
        return "Weather data unavailable."
    return (
        f"{weather['emoji']} {weather['description']} in {weather['city']}, "
        f"{weather['temp']}°C (feels like {weather['feels_like']}°C), "
        f"humidity {weather['humidity']}%, wind {weather['wind_speed']} km/h"
    )


def get_greeting() -> str:
    """Generate EDITH's full wake-up greeting with time, date, and weather."""
    now = datetime.datetime.now()

    # Time in 12-hour format
    time_str = now.strftime("%I:%M %p")
    # Full date
    date_str = now.strftime("%A, %d %B %Y")
    # Time-of-day greeting
    hour = now.hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    elif hour < 21:
        greeting = "Good evening"
    else:
        greeting = "Good night"

    # Weather
    w_result = get_current_weather()
    weather = w_result.value if w_result.ok else None
    weather_line = format_weather(weather)

    return (
        f"{greeting}, Vaibhav. The time is {time_str}, {date_str}.\n"
        f"Weather: {weather_line}\n"
        f"How can I help you, Boss?"
    )


if __name__ == "__main__":
    print("[EDITH Weather] Testing...\n")
    r = get_current_weather()
    if r.ok:
        print(f"Location: {r.value['city']}, {r.value['region']}")
        print(f"Weather:  {format_weather(r.value)}")
    else:
        print(f"Weather fetch failed: {r.error}")
    print()
    print(get_greeting())
