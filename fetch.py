#!/usr/bin/env python3
"""抓取北京市花粉监测数据，整合输出 data/latest.json。

仅使用 Python 3 标准库（urllib/json），供 GitHub Actions 每小时运行。
关键接口 latestPollenLevels 失败时以非零码退出，不覆盖已有的好数据；
其余接口失败时沿用上一份 latest.json 中对应部分（若有）。
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://pollenwechat.bjpws.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BeijingPollenMonitor/1.0; +github-actions)"}
TIMEOUT = 15
RETRIES = 3
BJT = timezone(timedelta(hours=8))

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "latest.json")


def fetch_json(url):
    """GET JSON，15s 超时，最多 3 次重试，指数退避。成功返回 data 字段。"""
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("code") != 200:
                raise ValueError("code=%r msg=%r" % (payload.get("code"), payload.get("msg")))
            return payload.get("data")
        except Exception as exc:
            last_err = exc
            print("请求失败(%d/%d) %s: %s" % (attempt + 1, RETRIES, url, exc), file=sys.stderr)
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError("多次请求失败 %s: %s" % (url, last_err))


def level_of_value(legends, value):
    for lg in legends:
        mn, mx = lg.get("minValue"), lg.get("maxValue")
        if isinstance(mn, (int, float)) and isinstance(mx, (int, float)) and mn <= value <= mx:
            try:
                return int(lg.get("level"))
            except (TypeError, ValueError):
                return None
    return None


def load_previous():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    previous = load_previous()

    # 1. 关键接口：16 站点最新读数。失败则退出，不覆盖旧数据。
    try:
        latest = fetch_json(BASE + "/api/pollen/obs/latestPollenLevels")
        if not isinstance(latest, list) or not latest:
            raise ValueError("返回数据为空")
    except Exception as exc:
        print("关键接口 latestPollenLevels 失败，保留旧数据并退出: %s" % exc, file=sys.stderr)
        return 1

    stations = [{
        "staId": str(s.get("staId")),
        "staName": s.get("staName"),
        "lon": s.get("lon"),
        "lat": s.get("lat"),
        "level": s.get("hfHLv"),
        "value": s.get("hfH"),
        "time": s.get("nttimeter"),
    } for s in latest]

    # 2. 等级定义
    try:
        legends = (fetch_json(BASE + "/v1/pollen/legends") or {}).get("legends") or []
        for lg in legends:
            if isinstance(lg.get("chLevel"), str):
                lg["chLevel"] = lg["chLevel"].strip()
    except Exception as exc:
        print("legends 接口失败，沿用旧数据: %s" % exc, file=sys.stderr)
        legends = previous.get("legends") or []

    # 3. 每站点 24 小时逐时历史
    histories = {}
    old_histories = previous.get("histories") or {}
    for st in stations:
        sid = st["staId"]
        try:
            rows = fetch_json(BASE + "/api/pollen/obs/history24?staId=" + sid) or []
            rows = sorted(rows, key=lambda r: r.get("nttimeter") or "")
            histories[sid] = [{
                "time": r.get("nttimeter"),
                "level": r.get("hfHLv"),
                "value": r.get("hfH"),
                "advice": r.get("advice"),
            } for r in rows]
        except Exception as exc:
            print("history24(staId=%s) 失败，沿用旧数据: %s" % (sid, exc), file=sys.stderr)
            histories[sid] = old_histories.get(sid, [])
        time.sleep(0.2)

    # 4. 全市概况：由 16 站点实时读数计算，并附 pollens 接口的北京分区数据
    levels = [st["level"] for st in stations if isinstance(st.get("level"), (int, float))]
    values = [st["value"] for st in stations if isinstance(st.get("value"), (int, float))]
    city_level = int(sum(levels) / len(levels) + 0.5) if levels else None
    legend_map = {str(lg.get("level")): lg for lg in legends}
    city_legend = legend_map.get(str(city_level)) or {}

    districts = []
    try:
        pollens = fetch_json(BASE + "/v1/weatherPollen/pollens") or {}
        for d in pollens.get("beijing") or []:
            try:
                v = int(d.get("pollen"))
            except (TypeError, ValueError):
                v = None
            districts.append({
                "name": (d.get("name") or "").split("-")[0],
                "value": v,
                "level": level_of_value(legends, v) if v is not None else None,
                "time": d.get("dataTime"),
            })
    except Exception as exc:
        print("pollens 接口失败，沿用旧数据: %s" % exc, file=sys.stderr)
        districts = (previous.get("citywide") or {}).get("districts") or []

    citywide = {
        "level": city_level,
        "levelText": city_legend.get("chLevel"),
        "avgValue": round(sum(values) / len(values), 1) if values else None,
        "obsTime": max((st["time"] for st in stations if st.get("time")), default=None),
        "advice": city_legend.get("description"),
        "districts": districts,
    }

    # 5. 分区预报：values["24"] 按起报时间分组，vti=HOUR_24，预报日 = 起报时间 + 24h
    forecast = []
    try:
        fc = fetch_json(BASE + "/v1/pollen/forecast?plantCode=zongleibie") or {}
        grouped = (fc.get("values") or {}).get("24") or {}
        for data_time in sorted(grouped):
            try:
                date = (datetime.strptime(data_time, "%Y%m%d%H%M") + timedelta(hours=24)).strftime("%Y-%m-%d")
            except ValueError:
                date = data_time
            forecast.append({
                "date": date,
                "dataTime": data_time,
                "areas": [{
                    "areaCode": e.get("areaCode"),
                    "areaName": e.get("areaName"),
                    "level": e.get("val"),
                } for e in grouped[data_time] or []],
            })
    except Exception as exc:
        print("forecast 接口失败，沿用旧数据: %s" % exc, file=sys.stderr)
        forecast = previous.get("forecast") or []

    out = {
        "updatedAt": datetime.now(BJT).isoformat(timespec="seconds"),
        "legends": legends,
        "stations": stations,
        "histories": histories,
        "citywide": citywide,
        "forecast": forecast,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)

    print("更新完成，抓取时间 %s" % out["updatedAt"])
    for st in sorted(stations, key=lambda s: s["staId"]):
        lg = legend_map.get(str(st.get("level"))) or {}
        print("  %-4s staId=%s  等级 %s(%s)  浓度 %s" % (
            st.get("staName"), st.get("staId"), st.get("level"),
            lg.get("chLevel") or "?", st.get("value")))
    ok_hist = sum(1 for v in histories.values() if v)
    print("站点 %d 个（历史序列 %d 个成功），预报 %d 天 -> %s" % (
        len(stations), ok_hist, len(forecast), os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
