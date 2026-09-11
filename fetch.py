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
HISTORY_OUT = os.path.join(ROOT, "data", "history.json")
RETENTION_DAYS = 7   # 累积历史只保留最近 7 天
FORECAST_STEPS = 12  # 预测未来小时数
TREND_DECAY = 0.7    # 趋势修正随预测步长的衰减系数


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


def calibrate_level_fn(pairs):
    """从 (value, level) 实测对拟合 value -> level 的单调映射，用于预测值定级。

    站点实测的 hfH 浓度值与 legends 的浓度区间量纲不一致（实测值量级远小于区间，
    直接按区间映射会使预测等级恒为 1），故改用本地校准：取每个等级观测值的中位数，
    按等级顺序做累积最大值单调化，预测值归入中位数最近的等级（映射随 value 单调不减）。
    有效等级不足 2 个时返回 None，由调用方回退。
    """
    by_level = {}
    for value, level in pairs:
        if isinstance(value, (int, float)) and isinstance(level, (int, float)) and 1 <= level <= 5:
            by_level.setdefault(int(level), []).append(value)
    if len(by_level) < 2:
        return None

    levels = sorted(by_level)
    medians = []
    for lv in levels:
        vals = sorted(by_level[lv])
        mid = len(vals) // 2
        med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        medians.append(max(med, medians[-1]) if medians else med)

    def to_level(value):
        return min(zip(medians, levels), key=lambda m: abs(m[0] - value))[1]

    return to_level


def load_previous():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_time(s):
    """'YYYY-MM-DD HH:00:00'（北京时间字符串）-> naive datetime；解析失败返回 None。"""
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def load_history():
    """读取累积历史 data/history.json；损坏或结构不对时返回空，不致命。"""
    try:
        with open(HISTORY_OUT, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print("history.json 损坏，重新累积: %s" % exc, file=sys.stderr)
        return {}


def update_history(old, stations, histories, now):
    """把本次实测点合并进累积历史：按 time 去重排序，只保留最近 RETENTION_DAYS 天。"""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    merged = {}

    def add(sid, time_str, level, value):
        dt = parse_time(time_str)
        if dt is None or dt < cutoff or not isinstance(value, (int, float)):
            return
        merged.setdefault(str(sid), {})[time_str] = {
            "time": time_str, "level": level, "value": value,
        }

    if isinstance(old, dict):
        for sid, rows in old.items():
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict):
                        add(sid, r.get("time"), r.get("level"), r.get("value"))
    for st in stations:
        add(st["staId"], st.get("time"), st.get("level"), st.get("value"))
    for sid, rows in (histories or {}).items():
        for r in rows:
            add(sid, r.get("time"), r.get("level"), r.get("value"))

    return {sid: [pts[k] for k in sorted(pts)] for sid, pts in merged.items()}


def predict_station(station, rows, level_fn):
    """统计预测未来 12 小时逐时浓度（纯统计估计，仅供参考）。

    方法：pred(h) = w * 昨日同时刻实测值 + (1 - w) * (当前值 + 衰减趋势)
    - 主信号：昨日同时刻（预测目标时刻 -24h）的实测值，反映花粉的日变化规律
    - 修正项：最近 3 小时实测的最小二乘斜率，按 TREND_DECAY^k 随步长累积衰减，
      越远的预测步趋势权重越小，避免线性外推发散
    - w 随步长 h 从 0.4 渐增至 0.8：越往后越信日变化规律
    - 缺昨日同时刻数据时回退为持续性 + 衰减趋势
    - 预测值 clamp 到 [0, 1000]，等级由 level_fn（本地校准，见 calibrate_level_fn）映射
    """
    pts = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        dt = parse_time(r.get("time"))
        if dt is not None and isinstance(r.get("value"), (int, float)):
            pts.append((dt, r["value"]))
    cur_dt = parse_time(station.get("time"))
    if cur_dt is not None and isinstance(station.get("value"), (int, float)):
        pts.append((cur_dt, station["value"]))
    if not pts:
        return []

    by_time = dict(pts)
    t0 = max(by_time)
    v0 = by_time[t0]

    # 最近 3 小时实测的最小二乘斜率（单位：浓度/小时；点数不足则为 0）
    recent = [(dt, v) for dt, v in pts if 0 <= (t0 - dt).total_seconds() <= 3 * 3600]
    slope = 0.0
    if len(recent) >= 2:
        xs = [(dt - t0).total_seconds() / 3600.0 for dt, _ in recent]
        ys = [v for _, v in recent]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denom = sum((x - mx) ** 2 for x in xs)
        if denom > 0:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom

    out = []
    for h in range(1, FORECAST_STEPS + 1):
        target = t0 + timedelta(hours=h)
        w = 0.4 + 0.4 * (h - 1) / (FORECAST_STEPS - 1)
        trend = slope * sum(TREND_DECAY ** k for k in range(h))
        persistence = v0 + trend
        yest = by_time.get(target - timedelta(hours=24))
        pred = w * yest + (1 - w) * persistence if yest is not None else persistence
        value = round(min(1000.0, max(0.0, pred)), 1)
        out.append({
            "time": target.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level_fn(value),
            "value": value,
        })
    return out


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

    # 3.5 累积滚动历史（最近 7 天），写入 data/history.json；损坏/缺失均不致命
    now_bj = datetime.now(BJT).replace(tzinfo=None)
    history = update_history(load_history(), stations, histories, now_bj)
    try:
        tmp_h = HISTORY_OUT + ".tmp"
        with open(tmp_h, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_h, HISTORY_OUT)
    except Exception as exc:
        print("history.json 写入失败（不致命）: %s" % exc, file=sys.stderr)

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

    # 6. 统计预测未来 12 小时（方法见 predict_station 注释；纯统计估计，仅供参考）
    #    预测值定级用本地校准：站点自身历史 (value, level) 对 -> 全局所有站点 -> 当前实测等级
    global_fn = calibrate_level_fn(
        (r.get("value"), r.get("level")) for rows in history.values() for r in rows)
    predictions = {}
    old_predictions = previous.get("predictions") or {}
    for st in stations:
        try:
            local_fn = calibrate_level_fn(
                (r.get("value"), r.get("level")) for r in history.get(st["staId"]) or [])
            cur_level = st.get("level") if isinstance(st.get("level"), (int, float)) else None

            def level_fn(v, local=local_fn, fallback=global_fn, cur=cur_level):
                if local is not None:
                    return local(v)
                if fallback is not None:
                    return fallback(v)
                return cur

            predictions[st["staId"]] = predict_station(st, history.get(st["staId"]) or [], level_fn)
        except Exception as exc:
            print("预测生成失败(staId=%s，不致命): %s" % (st["staId"], exc), file=sys.stderr)
            predictions[st["staId"]] = old_predictions.get(st["staId"], [])

    out = {
        "updatedAt": datetime.now(BJT).isoformat(timespec="seconds"),
        "legends": legends,
        "stations": stations,
        "histories": histories,
        "citywide": citywide,
        "forecast": forecast,
        "predictions": predictions,
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
    hist_points = sum(len(v) for v in history.values())
    ok_pred = sum(1 for v in predictions.values() if len(v) == FORECAST_STEPS)
    print("站点 %d 个（历史序列 %d 个成功），预报 %d 天；累积历史 %d 点，预测 %d/%d 站点 -> %s" % (
        len(stations), ok_hist, len(forecast), hist_points, ok_pred,
        len(stations), os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
