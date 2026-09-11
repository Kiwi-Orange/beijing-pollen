#!/usr/bin/env python3
"""一次性回补中国天气网逐日花粉指数（2010-01-01 起）到 data/archive/daily-index.csv。

不进 GitHub Actions 定时任务；日常增量由 fetch.py 维护（最近 7 天滚动合并）。
分年度段抓取（每段约 2 年），按 date 去重排序，重复运行幂等。

用法：python3 backfill_daily.py [起始日期 默认 2010-01-01] [结束日期 默认昨天]
"""

import os
import sys
import time
from datetime import datetime, timedelta

from fetch import ARCHIVE_DIR, DAILY_HEADER, fetch_daily_index, merge_archive, parse_date

DEFAULT_START = "2010-01-01"
CHUNK_DAYS = 730  # 每段约 2 年，URL 不宜过长


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_START
    end = sys.argv[2] if len(sys.argv) > 2 else (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if parse_date(start) is None or parse_date(end) is None or start > end:
        print("日期参数无效: %s ~ %s" % (start, end), file=sys.stderr)
        return 1

    path = os.path.join(ARCHIVE_DIR, "daily-index.csv")
    cur = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    total = 0
    failed = []
    while cur <= end_dt:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS), end_dt)
        s, e = cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        try:
            rows = fetch_daily_index(s, e)
            n = merge_archive(path, DAILY_HEADER, list(rows.values()),
                              key_fn=lambda r: r[0], sort_fn=lambda r: r[0])
            print("%s ~ %s: 获取 %d 天，累计 %d 行" % (s, e, len(rows), n))
            total += len(rows)
        except Exception as exc:
            print("%s ~ %s 失败（跳过，可重跑回补）: %s" % (s, e, exc), file=sys.stderr)
            failed.append((s, e))
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.5)

    print("回补完成：%s ~ %s，共获取 %d 天 -> %s" % (start, end, total, os.path.relpath(path)))
    if failed:
        print("有 %d 个分段失败：%s" % (len(failed), failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
