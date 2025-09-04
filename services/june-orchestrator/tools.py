def get_weather(city: str) -> str:
    # Replace with real API (OpenWeather, WeatherAPI, etc.)
    if city.lower() == "bogotá":
        return "Sunny, 25°C"
    return f"No weather data available for {city}"

def calculator(expression: str) -> str:
    try:
        result = eval(expression, {"__builtins__": {}})
        return str(result)
    except Exception:
        return "Error in calculation"
