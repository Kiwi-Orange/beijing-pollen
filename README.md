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

## 免责声明

本站为个人非营利信息展示项目，数据仅供参考，不构成医疗建议。
