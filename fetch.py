#!/usr/bin/env python3
"""抓取北京市花粉监测数据，整合输出 data/latest.json。

仅使用 Python 3 标准库（urllib/json），供 GitHub Actions 每小时运行。
关键接口 latestPollenLevels 失败时以非零码退出，不覆盖已有的好数据；
其余接口失败时沿用上一份 latest.json 中对应部分（若有）。
"""

import csv
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


def fetch_json(url, raw=False):
    """GET JSON，15s 超时，最多 3 次重试，指数退避。
    raw=False 时返回包装内的 data 字段（花粉平台）；raw=True 返回整个响应体（Open-Meteo 等）。"""
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if raw:
                return payload
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

    def typical(level):
        return to_level.medians.get(int(level))

    to_level.medians = dict(zip(levels, medians))
    to_level.typical = typical
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


def build_diurnal_profile(rows):
    """从站点累积历史构建昼夜曲线：各整点(0-23时)相对当天均值的偏差，多天同整点取中位数。

    返回 (profile, day_count)：profile 为 {hour: anomaly}，数据不足时可能为空字典；
    day_count 为可用完整天（>=12 个整点观测）的数量，供调用方判断稳健性。
    """
    days = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        dt = parse_time(r.get("time"))
        v = r.get("value")
        if dt is not None and isinstance(v, (int, float)):
            days.setdefault(dt.date(), {})[dt.hour] = v
    profile = {}
    day_count = 0
    for hours in days.values():
        if len(hours) >= 12:
            day_count += 1
    if day_count:
        for h in range(24):
            vals = []
            for hours in days.values():
                if len(hours) >= 12 and h in hours:
                    mean = sum(hours.values()) / len(hours)
                    vals.append(hours[h] - mean)
            if vals:
                vals.sort()
                mid = len(vals) // 2
                profile[h] = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return profile, day_count


def weather_modifiers(payload, now):
    """从 Open-Meteo 逐时响应提取预测修正因子（经验系数，论文使用前需自行校准）。

    返回 (rain_factor, wind_factor, rainy_hours)：
    - rain_factor：最近 6 小时累计降水 >= 5mm 取 0.35，>= 1mm 取 0.6，否则 1（雨后冲刷）
    - wind_factor：当前风速 >= 6 m/s 取 0.85，否则 1（扩散稀释）
    - rainy_hours：未来 12 小时内降水 > 0.5mm 的整点集合（这些小时再乘 0.75）
    解析失败或数据缺失时返回 (1.0, 1.0, set())，即无修正。
    """
    try:
        hourly = (payload or {}).get("hourly") or {}
        times = hourly.get("time") or []
        prec = hourly.get("precipitation") or []
        wind = hourly.get("wind_speed_10m") or []
        pts = []
        for i, ts in enumerate(times):
            dt = parse_time(str(ts).replace("T", " ") + ":00")
            if dt is None:
                continue
            p = prec[i] if isinstance(prec, list) and i < len(prec) and isinstance(prec[i], (int, float)) else 0.0
            w = wind[i] if isinstance(wind, list) and i < len(wind) and isinstance(wind[i], (int, float)) else 0.0
            pts.append((dt, p, w))
        if not pts:
            return 1.0, 1.0, set()
        rain6 = sum(p for dt, p, w in pts if 0 <= (now - dt).total_seconds() <= 6 * 3600)
        rain_factor = 0.35 if rain6 >= 5 else (0.6 if rain6 >= 1 else 1.0)
        cur_wind = max((w for dt, p, w in pts if abs((now - dt).total_seconds()) <= 3600), default=0.0)
        wind_factor = 0.85 if cur_wind >= 6 else 1.0
        rainy = set(dt for dt, p, w in pts if 0 < (dt - now).total_seconds() <= 12 * 3600 and p > 0.5)
        return rain_factor, wind_factor, rainy
    except Exception:
        return 1.0, 1.0, set()


def predict_station(station, rows, level_fn, profile=None, wmod=None, hint_value=None):
    """统计预测未来 12 小时逐时浓度（纯统计估计，仅供参考）。

    方法：pred(h) = w·昼夜信号 + (1-w)·(当前值 + 衰减趋势)，再叠加气象修正与官方预报约束。
    - 昼夜信号：当日已观测均值 + 近 7 天平均昼夜曲线在目标整点的偏差（build_diurnal_profile）；
      曲线缺失时回退为昨日同时刻实测值
    - 趋势修正：最近 3 小时实测的最小二乘斜率，按 TREND_DECAY^k 随步长累积衰减，避免发散
    - w 随步长 h 从 0.4 渐增至 0.8：越往后越信昼夜规律
    - 气象修正（经验系数）：雨后冲刷 rain_factor 随步长线性恢复为 1；未来有降水的小时乘 0.75；
      大风扩散 wind_factor 恒定作用于全部步
    - 官方预报约束：落在次日的小时向官方预报等级对应的典型浓度 nudge 15%（hint_value 为 None 则跳过）
    - 预测值 clamp 到 [0, 1000]，等级由 level_fn（本地校准）映射
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

    # 当日均值（当天 0 点起已观测小时）；不足时回退近 24h 均值、再退回当前值
    today = [v for dt, v in pts if dt.date() == t0.date()]
    if today:
        day_mean = sum(today) / len(today)
    else:
        recent24 = [v for dt, v in pts if 0 <= (t0 - dt).total_seconds() <= 24 * 3600]
        day_mean = (sum(recent24) / len(recent24)) if recent24 else v0

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

    rain_factor, wind_factor, rainy_hours = wmod if wmod else (1.0, 1.0, set())
    out = []
    for h in range(1, FORECAST_STEPS + 1):
        target = t0 + timedelta(hours=h)
        w = 0.4 + 0.4 * (h - 1) / (FORECAST_STEPS - 1)
        trend = slope * sum(TREND_DECAY ** k for k in range(h))
        persistence = v0 + trend
        if profile and target.hour in profile:
            diurnal = day_mean + profile[target.hour]
        else:
            yest = by_time.get(target - timedelta(hours=24))
            diurnal = yest if yest is not None else persistence
        pred = w * diurnal + (1 - w) * persistence
        # 气象修正：雨后冲刷随步长线性恢复（h=1 时近全效，h=12 时基本复原）
        rf = 1.0 + (rain_factor - 1.0) * (1 - h / (FORECAST_STEPS + 1))
        pred *= rf * wind_factor
        if target in rainy_hours:
            pred *= 0.75
        # 官方次日预报约束：轻微 nudge 15%
        if hint_value is not None:
            pred += 0.15 * (hint_value - pred)
        value = round(min(1000.0, max(0.0, pred)), 1)
        out.append({
            "time": target.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level_fn(value),
            "value": value,
        })
    return out


ARCHIVE_DIR = os.path.join(ROOT, "data", "archive")
POLLEN_HEADER = ["time", "sta_id", "sta_name", "lon", "lat", "level", "value"]
WEATHER_HEADER = ["time", "sta_id", "temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"]
WEATHER_FIELDS = WEATHER_HEADER[2:]
DAILY_HEADER = ["date", "level_code", "level", "level_msg", "color"]
DAILY_URL = ("https://graph.weatherdt.com/ty/pollen/v2/hfindex.html"
             "?eletype=1&city=beijing&start=%s&end=%s&predictFlag=false")
DAILY_HISTORY_DAYS = 365  # 写入 latest.json 供前端季节走势的天数


def parse_date(s):
    """'YYYY-MM-DD' -> date；解析失败返回 None。"""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def fetch_daily_index(start, end):
    """中国天气网逐日花粉指数（原始 JSON，无 code 包装）。
    返回 {date: [date, level_code, level, level_msg, color]}；'暂无' 等记录原样保留。"""
    payload = fetch_json(DAILY_URL % (start, end), raw=True)
    out = {}
    for item in (payload or {}).get("dataList") or []:
        date = item.get("addTime")
        if parse_date(date) is None:
            continue
        out[date] = [date, item.get("levelCode"), item.get("level"),
                     item.get("levelMsg"), item.get("color")]
    return out


def update_daily_archive(now):
    """合并最近 7 天逐日指数进 daily-index.csv，并返回最近 365 天列表供 latest.json。"""
    start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    new = fetch_daily_index(start, end)
    path = os.path.join(ARCHIVE_DIR, "daily-index.csv")
    merge_archive(path, DAILY_HEADER, list(new.values()),
                  key_fn=lambda r: r[0], sort_fn=lambda r: r[0])
    cutoff = (now - timedelta(days=DAILY_HISTORY_DAYS)).strftime("%Y-%m-%d")
    history = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            if next(reader, None) == DAILY_HEADER:
                for row in reader:
                    if len(row) == len(DAILY_HEADER) and row[0] >= cutoff:
                        try:
                            level_code = int(row[1])
                        except ValueError:
                            level_code = None  # '暂无' 等记录 levelCode 缺失，保留原样
                        history.append({"date": row[0], "levelCode": level_code, "level": row[2]})
    except Exception as exc:
        print("读取 daily-index.csv 失败（不致命）: %s" % exc, file=sys.stderr)
    return history


def merge_archive(path, header, new_rows, key_fn=None, sort_fn=None):
    """合并写入归档 CSV：读已有内容 -> 按键去重（新行优先）-> 原子重写。
    已有文件损坏/表头不符时打印警告并只写新数据，不崩溃。返回文件总行数。
    key_fn/sort_fn 作用于字符串化后的行，默认键 (sta_id, time)、按 (time, sta_id) 排序。"""
    if not new_rows:
        return 0
    key_fn = key_fn or (lambda r: (r[1], r[0]))
    sort_fn = sort_fn or (lambda r: (r[0], r[1]))
    rows = {}
    if os.path.exists(path):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                if next(reader, None) != header:
                    raise ValueError("表头不符")
                for row in reader:
                    if len(row) == len(header):
                        rows[key_fn(row)] = row
        except Exception as exc:
            print("归档文件损坏，仅用新数据重写 %s: %s" % (os.path.basename(path), exc), file=sys.stderr)
            rows = {}
    for row in new_rows:
        row = ["" if v is None else str(v) for v in row]
        rows[key_fn(row)] = row
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for key in sorted(rows, key=lambda k: sort_fn(rows[k])):
            writer.writerow(rows[key])
    os.replace(tmp, path)
    return len(rows)


def archive_pollen(stations, histories):
    """把本次所有实测点（当前值 + 每站 24h 逐时历史）按月归档到 pollen-YYYY-MM.csv。
    两个来源合并去重，可在某次运行失败时回补缺口。"""
    meta = {st["staId"]: st for st in stations}
    by_month = {}

    def add(sid, time_str, level, value):
        if parse_time(time_str) is None or not isinstance(value, (int, float)):
            return
        st = meta.get(sid) or {}
        row = [time_str, sid, st.get("staName"), st.get("lon"), st.get("lat"), level, value]
        by_month.setdefault(time_str[:7], []).append(row)

    for st in stations:
        add(st["staId"], st.get("time"), st.get("level"), st.get("value"))
    for sid, rows in (histories or {}).items():
        for r in rows:
            add(sid, r.get("time"), r.get("level"), r.get("value"))

    files = []
    for month, rows in sorted(by_month.items()):
        n = merge_archive(os.path.join(ARCHIVE_DIR, "pollen-%s.csv" % month), POLLEN_HEADER, rows)
        files.append("pollen-%s.csv(%d 行)" % (month, n))
    print("花粉归档完成：%s" % ", ".join(files))


def archive_weather(stations, now, payloads):
    """Open-Meteo 逐小时气象（免费、无需 key）归档到 weather-YYYY-MM.csv。
    使用 main() 已抓取的 payloads（与预测共用），只保留 <= 当前时刻的部分；
    单站缺失跳过，整体失败不致命。"""
    added = 0
    for st in stations:
        sid = st["staId"]
        payload = payloads.get(sid)
        if payload is None:
            continue
        try:
            hourly = (payload or {}).get("hourly") or {}
            times = hourly.get("time") or []
            by_month = {}
            for i, ts in enumerate(times):
                # timezone=Asia/Shanghai 返回北京本地时间 "2026-09-11T09:00"，转成与花粉一致的格式
                dt = parse_time(str(ts).replace("T", " ") + ":00")
                if dt is None or dt > now:
                    continue  # 未来时刻不归档
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                row = [time_str, sid]
                for f_ in WEATHER_FIELDS:
                    vals = hourly.get(f_)
                    row.append(vals[i] if isinstance(vals, list) and i < len(vals) else None)
                by_month.setdefault(time_str[:7], []).append(row)
            for month, rows in by_month.items():
                merge_archive(os.path.join(ARCHIVE_DIR, "weather-%s.csv" % month), WEATHER_HEADER, rows)
                added += len(rows)
        except Exception as exc:
            print("Open-Meteo 站点 %s 归档失败，跳过: %s" % (sid, exc), file=sys.stderr)
    print("气象归档完成：本次归档 %d 点（%d 站）" % (added, len(stations)))


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

    # 5.5 气象数据（Open-Meteo）：预测修正与归档共用，整体失败不致命
    weather_payloads = {}
    for st in stations:
        sid = st["staId"]
        lon, lat = st.get("lon"), st.get("lat")
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            continue
        try:
            weather_payloads[sid] = fetch_json(
                "https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                "&hourly=%s&timezone=Asia%%2FShanghai&past_days=2&forecast_days=1"
                % (lat, lon, ",".join(WEATHER_FIELDS)), raw=True)
        except Exception as exc:
            print("Open-Meteo 站点 %s 失败（不致命）: %s" % (sid, exc), file=sys.stderr)
        time.sleep(0.5)

    # 6.0 预测自检：上一份预测 vs 本次实测（history24 + 当前值），配对计算平均误差
    prev_preds = previous.get("predictions") or {}
    prev_skill = previous.get("forecastSkill") or {}
    errs_v, errs_l, n_pairs = [], [], 0
    obs_map = {}
    for st in stations:
        m = {}
        for r in histories.get(st["staId"]) or []:
            m[r.get("time")] = (r.get("value"), r.get("level"))
        if st.get("time"):
            m[st["time"]] = (st.get("value"), st.get("level"))
        obs_map[st["staId"]] = m
    for sid, preds in prev_preds.items():
        m = obs_map.get(sid) or {}
        for p in preds:
            if not isinstance(p, dict) or parse_time(p.get("time")) is None:
                continue
            if parse_time(p["time"]) > now_bj:
                continue
            obs = m.get(p["time"])
            if not obs or not isinstance(p.get("value"), (int, float)):
                continue
            ov, ol = obs
            if isinstance(ov, (int, float)):
                errs_v.append(abs(p["value"] - ov))
                n_pairs += 1
            if isinstance(ol, (int, float)) and isinstance(p.get("level"), (int, float)):
                errs_l.append(abs(p["level"] - ol))
    if n_pairs:
        forecast_skill = {
            "checkedAt": datetime.now(BJT).isoformat(timespec="seconds"),
            "N": n_pairs,
            "maeValue": round(sum(errs_v) / len(errs_v), 1) if errs_v else None,
            "maeLevel": round(sum(errs_l) / len(errs_l), 2) if errs_l else None,
        }
        print("预测自检：配对 %d 点，MAE(浓度)=%s，MAE(等级)=%s" % (
            n_pairs, forecast_skill["maeValue"], forecast_skill["maeLevel"]))
    else:
        forecast_skill = prev_skill

    global_fn = calibrate_level_fn(
        (r.get("value"), r.get("level")) for rows in history.values() for r in rows)
    # 官方次日分区预报 -> 站点：对次日时段的预测做约束 nudge
    tomorrow = (now_bj + timedelta(days=1)).strftime("%Y-%m-%d")
    hint_by_area = {}
    for day in forecast:
        if day.get("date") == tomorrow:
            for a in (day.get("areas") or []):
                if a.get("areaName") and isinstance(a.get("level"), (int, float)):
                    hint_by_area[a["areaName"]] = min(int(a["level"]), 5)
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

            profile, _ = build_diurnal_profile(history.get(st["staId"]) or [])
            wmod = weather_modifiers(weather_payloads.get(st["staId"]), now_bj)
            hint_value = None
            hint_lv = hint_by_area.get(st.get("staName"))
            if hint_lv is not None:
                typ = getattr(local_fn, "typical", None) or getattr(global_fn, "typical", None)
                if typ is not None:
                    hint_value = typ(hint_lv)
            predictions[st["staId"]] = predict_station(
                st, history.get(st["staId"]) or [], level_fn,
                profile=profile or None, wmod=wmod, hint_value=hint_value)
        except Exception as exc:
            print("预测生成失败(staId=%s，不致命): %s" % (st["staId"], exc), file=sys.stderr)
            predictions[st["staId"]] = old_predictions.get(st["staId"], [])

    # 6.5 逐日花粉指数（中国天气网）：合并最近 7 天进 daily-index.csv 归档，
    #     并取最近 365 天写入 latest.json 供前端季节走势；失败不致命，沿用旧数据
    try:
        daily_history = update_daily_archive(now_bj)
    except Exception as exc:
        print("逐日指数更新失败（不致命），沿用旧数据: %s" % exc, file=sys.stderr)
        daily_history = previous.get("dailyHistory") or []

    out = {
        "updatedAt": datetime.now(BJT).isoformat(timespec="seconds"),
        "legends": legends,
        "stations": stations,
        "histories": histories,
        "citywide": citywide,
        "forecast": forecast,
        "predictions": predictions,
        "forecastSkill": forecast_skill,
        "dailyHistory": daily_history,
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

    # 7. 科研数据归档（花粉 + 气象）。在 latest.json 成功写入后执行；
    #    归档失败绝不影响网站数据，仅打印警告。
    try:
        archive_pollen(stations, histories)
    except Exception as exc:
        print("花粉归档失败（不致命）: %s" % exc, file=sys.stderr)
    try:
        archive_weather(stations, now_bj, weather_payloads)
    except Exception as exc:
        print("气象归档失败（不致命）: %s" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
