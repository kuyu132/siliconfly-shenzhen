"""Shenzhen weather -> bounded, explicitly illustrative ecological controls.

These coefficients are engineering choices, not fitted Drosophila physiology.
Network weather is model output at city coordinates, not an indoor sensor.
"""
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

SHANGHAI = timezone(timedelta(hours=8))
PRESETS = {
    "spring": dict(label="春 · 回南潮湿", temperature=22, humidity=92, rain=0.2, wind=8, hour=9, month=3, sunrise=6.45, sunset=18.5),
    "summer": dict(label="夏 · 午后阵雨", temperature=31, humidity=85, rain=3, wind=22, hour=14, month=7, sunrise=5.75, sunset=19.15),
    "autumn": dict(label="秋 · 干爽黄昏", temperature=25, humidity=48, rain=0, wind=10, hour=17, month=11, sunrise=6.5, sunset=17.7),
    "winter": dict(label="冬 · 冷空气", temperature=12, humidity=45, rain=0, wind=18, hour=10, month=1, sunrise=7.05, sunset=18),
    "night": dict(label="夜 · 城市入眠", temperature=23, humidity=72, rain=0, wind=5, hour=23, month=10, sunrise=6.3, sunset=17.95),
}


def clamp(value, lo, hi):
    return min(hi, max(lo, value))


def validated(raw):
    limits = dict(temperature=(-20, 50), humidity=(0, 100), rain=(0, 100),
                  wind=(0, 200), hour=(0, 23.999), month=(1, 12), sunrise=(0, 12), sunset=(12, 24))
    out = dict(raw)
    for key, (lo, hi) in limits.items():
        v = raw.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f"{key} 必须在 {lo}–{hi} 范围内")
        out[key] = float(v)
    if int(out["month"]) != out["month"]:
        raise ValueError("month 必须为整数")
    return out


def controls(weather):
    w = validated(weather)
    t, h, rain, wind = (w[k] for k in ("temperature", "humidity", "rain", "wind"))
    hour, rise, setting = w["hour"], w["sunrise"], w["sunset"]
    day = rise <= hour < setting
    dawn = math.exp(-((hour - rise - 0.8) / 1.5) ** 2)
    dusk = math.exp(-((hour - setting + 0.6) / 1.8) ** 2)
    rhythm = min(1, (0.55 if day else 0.28) + 0.45 * max(dawn, dusk))
    thermal = clamp(0.50 + (t - 10) * 0.035, 0.42, 1.15)
    heat = clamp(1 - max(0, t - 30) * 0.065, 0.45, 1)
    shelter = clamp(rain / 5 + wind / 90, 0, 0.85)
    activity = clamp(rhythm * thermal * heat * (1 - 0.48 * shelter), 0.16, 1.1)
    thirst = clamp(0.7 + (100 - h) / 90 + max(0, t - 24) / 12, 0.65, 2.3)
    development = clamp(thermal * heat * (0.7 + h / 300), 0.25, 1.3)
    explanation = []
    if not day: explanation.append("夜间降低活动驱动，进入休息节律")
    elif dawn > .4 or dusk > .4: explanation.append("接近日出或日落，活动节律增强")
    else: explanation.append("日间维持基础活动，午间相对平缓")
    if t < 18: explanation.append("低温降低运动节奏与演示发育速率")
    if t > 30: explanation.append("高温触发抑制项，避免温度越高越活跃")
    if rain > .5 or wind > 20: explanation.append("雨风提高避扰倾向，降低探索驱动")
    if h < 55: explanation.append("低湿度加快口渴积累，增加寻水需求")
    return dict(activity=round(activity, 4), tempo=round(clamp(thermal * heat, .42, 1.15), 4),
                thirst=round(thirst, 4), development=round(development, 4),
                sleep=not day, rain=rain, wind=wind, daylight=day,
                light=round((.85 if day else .18) * (1 - .4 * shelter), 4),
                explanation=explanation, model="illustrative-ecology-v1")


def fetch_weather(now=None):
    now = now or datetime.now(SHANGHAI)
    query = urlencode(dict(latitude=22.5431, longitude=114.0579,
        current="temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
        daily="sunrise,sunset", timezone="Asia/Shanghai", forecast_days=1, wind_speed_unit="kmh"))
    url = "https://api.open-meteo.com/v1/forecast?" + query
    import json
    with urlopen(url, timeout=12) as response:
        payload = json.load(response)
    c, daily = payload["current"], payload["daily"]
    stamp = datetime.fromisoformat(c["time"]).replace(tzinfo=SHANGHAI)
    if abs((now - stamp).total_seconds()) > 7200:
        raise ValueError("天气时间与当前时间相差超过两小时，拒绝标为当前天气")
    def hour(text):
        d = datetime.fromisoformat(text)
        if d.date() != stamp.date(): raise ValueError("日出日落日期不匹配")
        return d.hour + d.minute / 60
    units = payload.get("current_units", {})
    if units.get("temperature_2m") != "°C" or units.get("wind_speed_10m") != "km/h":
        raise ValueError("天气单位与约定不一致")
    w = validated(dict(label="深圳 · 当前天气", temperature=c["temperature_2m"],
        humidity=c["relative_humidity_2m"], rain=c["precipitation"], wind=c["wind_speed_10m"],
        hour=now.hour + now.minute / 60, month=now.month,
        sunrise=hour(daily["sunrise"][0]), sunset=hour(daily["sunset"][0])))
    w.update(source="Open-Meteo 天气模型", observed_at=stamp.isoformat(),
             fetched_at=now.isoformat(), source_url=url, weather_code=c["weather_code"])
    return w
