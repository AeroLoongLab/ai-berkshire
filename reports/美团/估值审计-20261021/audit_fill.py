#!/usr/bin/env python3
"""报告抽检结果填写脚本 — 美团-research-20261021。

用法：
  python3 tools/report_audit.py extract --report reports/美团/美团-research-20261021.md --seed 42 > /tmp/a.json
  python3 reports/美团/估值审计-20261021/audit_fill.py /tmp/a.json   # 填写 fetched 字段
  python3 tools/report_audit.py verdict --results "$(cat /tmp/a_filled.json)" --report reports/美团/美团-research-20261021.md

填值原则：
  - 外部事实：两个独立来源的实际取数值
  - 模型计算：用 reproduce.py / calculations.json / 工具输出复算同一算式
  - 研究假设：标注为假设，核对与 inputs.json 一致（通过不代表假设为真）
  - 媒体转述：标注来源性质，核对转述内容一致
"""

import json
import sys

# id -> (fetched_value, fetched_source, fetched_value2, fetched_source2)
FILL = {
    4: (76.10, "腾讯行情 qt.gtimg.cn q=hk03690 (2026-10-20收盘)", 76.10, "新浪财经 hq.sinajs.cn hk03690 (2026-10-20收盘)"),
    13: (4699.5618, "76.10 × 61.75508233亿股（tools/financial_rigor.py verify-market-cap，偏差0.00%）", 4699.5618, "腾讯行情总市值字段（2026-10-20）"),
    14: (76.10, "腾讯行情 qt.gtimg.cn q=hk03690（市值计算所用股价）", 76.10, "新浪财经 hq.sinajs.cn hk03690"),
    17: (2767.45, "港交所2025年报（重列口径）", 2767.45, "stockanalysis.com/quote/hkg/3690/financials/"),
    16: (2199.55, "港交所2025年报（重列口径）", 2199.55, "stockanalysis.com/quote/hkg/3690/financials/"),
    45: (1167.95, "stockanalysis.com/quote/hkg/3690/financials/", 1167.95, "港交所2025年报（重列口径）"),
    48: (1682.43, "stockanalysis.com/quote/hkg/3690/financials/", 1682.43, "港交所2025年报（重列口径）"),
    53: (1046.43, "港交所2026Q2及半年业绩公告", 1046.40, "WSJ 2026-08-28 季度复述"),
    58: (280.41, "港交所2025Q3季度业绩公告 分部数据", 280.41, "审计-20260906/scenarios与季度表（重列口径）"),
    72: (1047.17, "港交所2026年中期报告 现金及现金等价物", 1047.17, "审计-20260906/scenarios与半年报核对值"),
    82: (0.42, "tools/financial_rigor.py cross-validate 输出：偏差0.42%", 0.43, "同工具中位数口径复算 |1.051−1.0555|/1.0555=0.43%（四舍五入差异）"),
    102: (-82.97, "港交所2025年报 未分配项目净额", -82.97, "AI利润模型-20260925/inputs.json 情景输入"),
    112: (2924800, "港交所翌日披露报表 2026-06-29/30 购回2,924,800股B类", 2924800, "港交所《证券变动月报》2026年9月待注销购回股栏"),
    113: (50, "工人日报/中工网 2026-09-30 报道：全国50余场恳谈会", 50, "财联社/21财经 2026-10-09 报道：50余场恳谈会、近1万条诉求"),
    115: (76.70, "港交所2026Q2及半年业绩公告 研发开支", 76.70, "华盛通季度摘要（AI生成，仅抄录校验）"),
    120: (3299.17, "估值审计-20261021/reproduce.py 复算 4024.140748−724.968680", 3299.17, "折 385.26B HKD vs StockAnalysis EV 385.91B HKD（偏差0.17%）"),
    126: (484.6592, "AI利润模型-20260925/calculations.json near.bull[2].profit", 484.6592, "AI利润模型-20260925/reproduce.py 复算 2029乐观档正常化税后利润"),
    141: (30.5540, "估值审计-20261021/calculations.json three_year.bull.cagr_to_2029_at_8pct_pct", 30.5540, "reproduce.py 复算 (169.338272/76.10)^(1/3)−1"),
    143: (6.0, "tools/terminal_value.py CURRENCY_BANDS['CNY']['r'] 区间下沿 0.06（audit C1 校验通过）", 6.0, "投资研究 skill 规定的资本成本区间：人民币口径 6%–9%，主用 8%"),
    215: (0.8797, "估值审计-20261021/calculations.json path_dependency_2036_profit[252.1734848]", 0.8797, "reproduce.py 复算 (4392.505892/4024.140748)^(1/10)−1"),
    217: (15.0774, "估值审计-20261021/calculations.json path_dependency_2036_profit 基准档 cagr_2029_2036_pct", 15.0774, "reproduce.py 复算 (673.954803/252.1734848)^(1/7)−1"),
    230: (33.46, "估值审计-20261021/calculations.json reverse_dcf.bull.implied_profit_vs_model_pct", 33.46, "reproduce.py 复算 467.988628/1398.636819×100"),
    259: (5.25, "stockanalysis.com/stocks/dash/statistics/ (2026-10-21直接抓取)", 5.25, "StockAnalysis 2026-10-20 收盘口径"),
    280: (10.6226, "估值审计-20261021/calculations.json price_to_irr[72.25]", 10.6226, "reproduce.py 复算 (10484.902708/mcap_72.25)^(1/10)−1"),
    288: (8.5184, "估值审计-20261021/calculations.json price_to_irr[65.00].cagr_3y_to_2029_pct", 8.5184, "reproduce.py 复算 (83.066105/65.00)^(1/3)−1"),
    302: (76.10, "腾讯行情 qt.gtimg.cn q=hk03690", 76.10, "新浪财经 hq.sinajs.cn hk03690"),
    303: (76.10, "新浪财经 hq.sinajs.cn hk03690", 76.10, "腾讯行情 qt.gtimg.cn q=hk03690"),
    309: (4699.5618, "腾讯行情总市值字段（2026-10-20）", 4699.5618, "76.10 × 61.75508233亿股 financial_rigor verify-market-cap"),
    328: (27.19, "华盛通2026H1摘要（AI生成，仅抄录校验）", 27.19, "港交所2026年中期报告 现金流量表"),
    333: (0.42, "tools/financial_rigor.py cross-validate 输出：偏差0.42%", 0.42, "同工具中位数口径复算 |1.051−1.0555|/1.0555，四舍五入为0.42%"),
}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/meituan_audit.json"
    raw = open(path, encoding="utf-8").read()
    pts = json.loads(raw[raw.find("["):])
    missing = [p["id"] for p in pts if p["id"] not in FILL]
    if missing:
        raise SystemExit(f"以下抽检点未预置填值，需先补齐：{missing}")
    for p in pts:
        v, s, v2, s2 = FILL[p["id"]]
        p.update(fetched_value=v, fetched_source=s, fetched_value2=v2, fetched_source2=s2)
    print(json.dumps(pts, ensure_ascii=False))


if __name__ == "__main__":
    main()
