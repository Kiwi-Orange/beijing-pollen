# 北京实时花粉指数监测

一个纯静态网站，展示北京市 16 区实时花粉浓度等级、24 小时逐时趋势和未来分区预报。

- 数据来源：[北京市花粉监测公共服务平台](https://pollenwechat.bjpws.com)（公开接口，免鉴权）
- 更新机制：GitHub Actions 每小时运行一次 `fetch.py`，抓取数据并提交 `data/latest.json` 到仓库（见 `.github/workflows/update.yml`，也可在 Actions 页面手动触发）
- 前端：原生 HTML/CSS/JS，无任何外部依赖和 CDN，趋势图为手写 SVG

## 本地开发

```bash
python3 fetch.py            # 抓取数据，生成 data/latest.json（仅需 Python 3 标准库）
python3 -m http.server 8000 # 本地预览
# 打开 http://localhost:8000
```

## 部署

推送到 GitHub 后，在仓库 Settings → Pages 中选择从 `main` 分支根目录（`/`）部署即可。

## 数据说明

- `fetch.py` 抓取 5 个接口：16 站点最新读数、每站 24 小时逐时历史、等级定义、全市及全国花粉数据（提取北京部分）、16 区花粉总量等级预报
- 整合输出为单个 `data/latest.json`，包含抓取时间、等级定义、站点当前值、逐时历史、全市概况和分区预报
- 关键接口（最新读数）失败时任务以非零码退出，不覆盖旧数据；其余接口失败时沿用上一份数据
- 页面展示的所有时间均为北京时间，取自接口原始字符串，未做时区转换

## 预测方法 / Forecast Methodology

### 中文

**数据来源与累积**：GitHub Actions 每小时运行 `fetch.py`，把 16 个站点的最新读数与 24 小时逐时历史合并进 `data/history.json`，按小时去重排序，只保留最近 7 天。预测所需的长期历史即来自这个滚动累积文件。

**预测公式**：对每个站点，未来第 h 小时（h = 1…12）的浓度预测为

```
pred(h) = w(h) × 昼夜信号(h) + (1 − w(h)) × (当前值 + trend(h)) × 气象修正(h) + 官方约束
trend(h) = slope × Σ(k=0…h−1) 0.7^k        （衰减累积，封顶约 3.3×slope，防发散）
w(h)     = 0.4 + 0.4 × (h−1)/11            （随步长从 0.4 线性增至 0.8）
```

- `昼夜信号(h)`：当日已观测小时均值 + 近 7 天平均昼夜曲线在目标整点的偏差（各整点相对当天均值的中位数偏差，见 `build_diurnal_profile`）。相比早期版本「仅用昨日同时刻」，多天中位数对单日异常更稳健；曲线缺该整点数据时回退为昨日同时刻实测值
- `slope`：最近 3 小时实测值对时间的最小二乘斜率
- **气象修正**（Open-Meteo 逐时数据，经验系数，论文使用前请自行校准）：最近 6 小时累计降水 ≥ 5 mm 乘 0.35、≥ 1 mm 乘 0.6（雨后冲刷，随步长线性恢复为 1）；未来 12 小时内预报有降水的小时乘 0.75；当前风速 ≥ 6 m/s 乘 0.85（扩散稀释）
- **官方约束**：落在次日的小时向官方分区预报等级对应的该站典型浓度 nudge 15%（混合系数 0.15；典型浓度来自本地校准的中位数）
- 预测值 clamp 到 [0, 1000]

**等级校准**：站点实测的浓度值（量级 2–30）与官方 legends 的浓度区间（0–100…800+）量纲不一致，直接按区间映射会使预测等级恒为 1。因此改用本地校准：取该站累积历史中每个等级观测值的中位数，按等级顺序单调化后，预测值归入中位数最近的等级。回退链：站点本地校准 → 全局 16 站合并校准 → 该站当前实测等级。

**预测自检（forecastSkill）**：每次运行生成新预测前，把上一份预测与本次刚抓到的实测（history24 + 当前值）按时点配对，计算过去 24 小时预测的平均绝对误差（浓度值 MAE 与等级 MAE），存入 `latest.json` 的 `forecastSkill` 字段并展示在趋势图下方。当前样本量还很小（项目运行数天），数值仅供参考，会随运行时间逐渐稳定。

**局限性**：纯统计外推，气象修正系数为经验值；累积历史不足 24 小时时昼夜信号缺失，预测以持续性为主；花粉浓度受多种环境因素影响，预测可能与实际有较大偏差。

### English

**Data source & accumulation**: GitHub Actions runs `fetch.py` hourly, merging the latest readings and 24-hour history of all 16 stations into `data/history.json` (deduplicated by hour, rolling 7-day retention). Forecasts are computed from this accumulated history.

**Formula**: for each station, the predicted concentration h hours ahead (h = 1…12) is

```
pred(h) = w(h) × diurnal signal(h) + (1 − w(h)) × (current value + trend(h)) × weather adj.(h) + official nudge
trend(h) = slope × Σ(k=0…h−1) 0.7^k        (decaying accumulation, capped ≈ 3.3×slope)
w(h)     = 0.4 + 0.4 × (h−1)/11            (grows linearly from 0.4 to 0.8 with step)
```

- The `diurnal signal(h)` is today's observed mean plus the deviation of target hour h in a 7-day average diurnal profile (median per-hour anomaly from each day's mean; see `build_diurnal_profile`). Compared with the earlier same-hour-yesterday version, the multi-day median is more robust to single-day anomalies; when the profile lacks that hour, it falls back to the same hour yesterday
- `slope` is a least-squares fit over the last 3 hours of observations
- **Weather adjustments** (Open-Meteo hourly data; empirical coefficients — recalibrate before research use): 6-hour accumulated precipitation ≥ 5 mm multiplies by 0.35, ≥ 1 mm by 0.6 (rain washout, recovering linearly to 1 with step); hours with forecast precipitation > 0.5 mm multiply by 0.75; current wind ≥ 6 m/s multiplies by 0.85 (dispersion)
- **Official nudge**: hours falling on the next day are nudged 15% toward the station's typical concentration for the official district forecast level (typical values come from the local calibration medians)
- Predictions are clamped to [0, 1000]

**Level calibration**: the observed concentration values (roughly 2–30) do not match the official legend ranges (0–100…800+), so range-based mapping would always yield level 1. Instead, a local calibration is used: for each level, the median of that station's observed values is computed, monotonized in level order, and a predicted value is assigned the level with the nearest median. Fallback chain: per-station calibration → global calibration across all 16 stations → the station's current observed level.

**Forecast self-check (forecastSkill)**: before generating new predictions, each run pairs the previous run's predictions with the freshly fetched observations (24-hour history + current readings) by timestamp and computes the mean absolute error over the last 24 hours (concentration MAE and level MAE). The result is stored in `latest.json` under `forecastSkill` and shown below the trend chart. The sample size is still small (the project has only been running for days); treat the number as indicative — it will stabilize over time.

**Limitations**: pure statistical extrapolation; weather-adjustment coefficients are empirical; with less than 24 h of accumulated history the diurnal signal is unavailable and the forecast is mostly persistence. Actual pollen levels may differ significantly.

**免责声明 / Disclaimer**：预测为基于历史规律的统计估计，仅供参考，不构成任何防护或医疗依据。Forecasts are statistical estimates based on historical patterns, for reference only, and do not constitute medical or protective advice.

## 科研数据归档 / Research Data Archive

### 中文

每次运行除生成网站数据外，还会把实测数据追加归档到 `data/archive/`，供科研分析长期使用：

- `pollen-YYYY-MM.csv`：花粉实测，按观测时间归属月份。列：`time,sta_id,sta_name,lon,lat,level,value`（time 为北京时间 `YYYY-MM-DD HH:00:00`；level 为 1–5 级；value 为花粉浓度）
- `weather-YYYY-MM.csv`：逐小时气象。列：`time,sta_id,temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m`（单位：°C、%、mm、m/s），只归档不晚于运行时刻的实测部分
- `daily-index.csv`：**全市逐日花粉指数，已回补 2010-01-01 至今（`backfill_daily.py` 一次性回补，日常增量由 `fetch.py` 维护）**。列：`date,level_code,level,level_msg,color`。level_code 为 0–5（0 未检测到花粉 ~ 5 很高），当日未发布时为 -1 且 level 为「暂无」。注意：此文件为**日级全市口径**（中国天气网与北京同仁医院联合发布），与站点逐时数据（1–5 级）口径不同，分析时应分开处理

**去重与缺口回补**：按 `(sta_id, time)` 去重，每次运行时读取当月已有 CSV、合并新观测后原子重写整月文件；花粉归档同时合并最新读数与 24 小时逐时历史两个来源，因此某次运行失败产生的缺口会在后续运行自动回补。`daily-index.csv` 按 `date` 去重，每次运行合并最近 7 天。

**数据来源**：花粉站点数据 — 北京市花粉监测公共服务平台（pollenwechat.bjpws.com）；逐日指数 — 中国天气网（graph.weatherdt.com）；气象 — Open-Meteo（api.open-meteo.com，免费无需 key，逐站真实经纬度请求）。

**免责与引用建议**：数据为公开接口的原始归档，未做质量控制，使用前请自行检查异常值。引用建议注明「北京市花粉监测公共服务平台」与「Open-Meteo」及本仓库地址。

### English

Besides the website data, each run appends observations to monthly archives under `data/archive/` for long-term research use:

- `pollen-YYYY-MM.csv`: pollen observations, filed by observation month. Columns: `time,sta_id,sta_name,lon,lat,level,value` (time is Beijing time `YYYY-MM-DD HH:00:00`; level is 1–5; value is pollen concentration)
- `weather-YYYY-MM.csv`: hourly weather. Columns: `time,sta_id,temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m` (units: °C, %, mm, m/s); only timestamps up to the run time are archived
- `daily-index.csv`: **citywide daily pollen index, backfilled from 2010-01-01 to present** (one-off backfill via `backfill_daily.py`; incremental updates maintained by `fetch.py`). Columns: `date,level_code,level,level_msg,color`. `level_code` is 0–5 (0 = none detected, 5 = very high); -1 with level `暂无` means no report published that day. Note this file is a **daily, citywide series** (published by weather.com.cn together with Beijing Tongren Hospital) and uses a different scale than the 5-level station data — analyze them separately.

**Deduplication & gap backfill**: rows are deduplicated by `(sta_id, time)`; each run reads the current month's CSV, merges new observations and atomically rewrites it. Pollen archiving merges both the latest readings and the 24-hour hourly history, so gaps left by a failed run are backfilled automatically on later runs. `daily-index.csv` is deduplicated by `date`, merging the last 7 days on every run.

**Sources**: station pollen data — Beijing Public Pollen Monitoring Service Platform (pollenwechat.bjpws.com); daily index — weather.com.cn (graph.weatherdt.com); weather — Open-Meteo (api.open-meteo.com, free, no API key; per-station coordinates).

**Disclaimer & citation**: the archive is a raw dump of public APIs without quality control — check for outliers before use. When citing, please credit "Beijing Public Pollen Monitoring Service Platform" and "Open-Meteo", and link to this repository.

## 免责声明

本站为个人非营利信息展示项目，数据仅供参考，不构成医疗建议。
