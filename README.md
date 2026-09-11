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
pred(h) = w(h) × 昨日同时刻实测值 + (1 − w(h)) × (当前值 + trend(h))
trend(h) = slope × Σ(k=0…h−1) 0.7^k        （衰减累积，封顶约 3.3×slope，防发散）
w(h)     = 0.4 + 0.4 × (h−1)/11            （随步长从 0.4 线性增至 0.8）
```

- `昨日同时刻实测值`：预测目标时刻 −24h 的历史实测（刻画花粉的日变化规律）；该时刻缺数据时退化为「当前值 + trend(h)」的持续性外推
- `slope`：最近 3 小时实测值对时间的最小二乘斜率
- 预测值 clamp 到 [0, 1000]

**等级校准**：站点实测的浓度值（量级 2–30）与官方 legends 的浓度区间（0–100…800+）量纲不一致，直接按区间映射会使预测等级恒为 1。因此改用本地校准：取该站累积历史中每个等级观测值的中位数，按等级顺序单调化后，预测值归入中位数最近的等级。回退链：站点本地校准 → 全局 16 站合并校准 → 该站当前实测等级。

**局限性**：纯统计外推，未考虑降雨、大风冲刷等天气突变；累积历史不足 24 小时时「昨日同时刻」信号缺失，预测以持续性为主；花粉浓度受多种环境因素影响，预测可能与实际有较大偏差。

### English

**Data source & accumulation**: GitHub Actions runs `fetch.py` hourly, merging the latest readings and 24-hour history of all 16 stations into `data/history.json` (deduplicated by hour, rolling 7-day retention). Forecasts are computed from this accumulated history.

**Formula**: for each station, the predicted concentration h hours ahead (h = 1…12) is

```
pred(h) = w(h) × observed value at the same hour yesterday + (1 − w(h)) × (current value + trend(h))
trend(h) = slope × Σ(k=0…h−1) 0.7^k        (decaying accumulation, capped ≈ 3.3×slope)
w(h)     = 0.4 + 0.4 × (h−1)/11            (grows linearly from 0.4 to 0.8 with step)
```

- The same-hour-yesterday term captures the daily cycle; when missing, the forecast falls back to persistence (current value + trend(h))
- `slope` is a least-squares fit over the last 3 hours of observations
- Predictions are clamped to [0, 1000]

**Level calibration**: the observed concentration values (roughly 2–30) do not match the official legend ranges (0–100…800+), so range-based mapping would always yield level 1. Instead, a local calibration is used: for each level, the median of that station's observed values is computed, monotonized in level order, and a predicted value is assigned the level with the nearest median. Fallback chain: per-station calibration → global calibration across all 16 stations → the station's current observed level.

**Limitations**: pure statistical extrapolation; sudden weather changes (rain, strong wind) are not modeled; with less than 24 h of accumulated history the daily-cycle term is unavailable and the forecast is mostly persistence. Actual pollen levels may differ significantly.

**免责声明 / Disclaimer**：预测为基于历史规律的统计估计，仅供参考，不构成任何防护或医疗依据。Forecasts are statistical estimates based on historical patterns, for reference only, and do not constitute medical or protective advice.

## 免责声明

本站为个人非营利信息展示项目，数据仅供参考，不构成医疗建议。
