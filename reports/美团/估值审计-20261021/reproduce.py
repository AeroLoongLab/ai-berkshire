#!/usr/bin/env python3
"""美团（03690.HK）十年尺度估值复算 — 2026-10-21 基准日。

口径：现金流币种 CNY（人民币亿元），每股值再按即期汇率折港元。
退出倍数唯一来源：tools/terminal_value.py 的永续增长模型 PE(终值) = (1 - g/ROIC)/(r - g)。
IRR 由 tools/terminal_value.py irr 计算，本脚本只负责喂数与交叉验算。

零外部依赖，Python 标准库。运行：python3 reproduce.py
"""

import json
import os
import subprocess
import sys
from decimal import Decimal as D, getcontext

getcontext().prec = 28

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TV_TOOL = os.path.join(ROOT, "tools", "terminal_value.py")
FR_TOOL = os.path.join(ROOT, "tools", "financial_rigor.py")

# ---------------------------------------------------------------- 输入
IN = {
    # 行情（2026-10-20 收盘，腾讯行情 + 新浪财经双源一致）
    "price_HKD": D("76.10"),
    # 总股本：港交所《证券变动月报》2026年9月月报（2026-10-07 呈交）
    # A类 579,152,986 + B类 5,596,355,247 = 6,175,508,233 股
    # 另有 2026-06-29/30 回购的 2,924,800 股 B 类截至 2026-09-30 尚未注销，未从股本中扣除。
    "shares_100m": D("61.75508233"),
    # 参考：若 2,924,800 股待注销股份完成注销，则为 61.75583433 亿股
    "shares_100m_after_cancel": D("61.75583433"),
    # 汇率：中国货币网人民币汇率中间价 2026-10-20 为 1 港元 = 0.85628 人民币（官方口径）。
    # 第二源新浪财经即期 2026-10-21 为 0.85090（CNH 口径），差 0.63%，属中间价与即期、
    # CNY 与 CNH 的口径差异。取官方中间价，与本仓库既往美团报告口径一致。
    "fx_CNY_per_HKD": D("0.85628"),
    "fx_spot_CNH": D("0.85090"),
    # 资产负债表（2026-06-30，2026年半年报）
    "cash_equiv": D("1047.16797"),
    "st_invest": D("635.97373"),
    "debt_incl_lease": D("958.17302"),
    "strategic_invest_book": D("772.80786"),
    # 2036 正常化税后年利润（亿元）——沿用《AI利润模型-20260925》审计通过的模型输出
    "profit_2036": {"bear": D("38.93354207577497917078400"),
                    "base": D("673.95480284351865916620800"),
                    "bull": D("1398.63681883899537292012800")},
    # 2036 期末股东现金（亿元）与战略投资变现价值（亿元）
    "cash_2036": {"bear": D("100"), "base": D("500"), "bull": D("800")},
    "invest_2036": {"bear": D("100"), "base": D("250"), "bull": D("400")},
    # 资本成本 / ROIC / 永续增速（人民币口径）
    "r": D("0.08"),
    "roic": D("0.15"),
    "g": {"bear": D("0.01"), "base": D("0.02"), "bull": D("0.03")},
    # 派息率 − 稀释率。美团无稳定现金股息；股份薪酬约 76.74 亿/年（2026Q2 年化），
    # 若回购不恢复则净稀释约 1.9%/年（按今日市值计），故敏感性档取 -0.019。
    "payout_base": D("0"),
    "payout_dilution": D("-0.019"),
    # 反推隐含值用的 2029 三年情景（沿用分部模型）
    "profit_2029": {"bear": D("-55.23"), "base": D("252.1734848"), "bull": D("484.6592")},
    "pe_2029": {"bear": D("12"), "base": D("14.4444444444444444444444"), "bull": D("16")},
    "cash_2029": {"bear": D("0"), "base": D("500"), "bull": D("800")},
    "invest_2029": {"bear": D("100"), "base": D("250"), "bull": D("400")},
    # 核心收入工作基数与 2036 情景结构（用于反向 DCF）
    "core_rev_2026": D("2800"),
    "core_rev_2036": {"bear": D("3762.96586216354137737200"),
                      "base": D("5014.37355031999014092800"),
                      "bull": D("6628.61828885792825522800")},
    "core_margin_2036": {"bear": D("0.09"), "base": D("0.17"), "bull": D("0.22")},
    "new_biz_2036": {"bear": D("-30"), "base": D("80"), "bull": D("250")},
    "hq_2036": {"bear": D("-190"), "base": D("-170"), "bull": D("-200")},
    "finance_2036": {"bear": D("-20"), "base": D("-20"), "bull": D("-10")},
    "ai_pretax_2036": {"bear": D("-50"), "base": D("100"), "bull": D("250")},
    "tax_rate": D("0.20"),
}


def run_tool(script, *args):
    """调用项目工具，返回 stdout。工具输出是证据，报告引用其中的算式。"""
    cmd = [sys.executable, script] + [str(a) for a in args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode not in (0, 1):
        raise RuntimeError(f"工具失败 {cmd}: {res.stderr[:400]}")
    return res.stdout, res.returncode


def exit_pe(roic, g, r):
    """与 terminal_value.py 同式，供脚本内自洽复算（工具输出另行留档）。"""
    spread = r - g
    if spread <= 0:
        return None
    return (D(1) - g / roic) / spread


def irr_from_tool(profit, mcap, pe, years=10, payout=0.0):
    """调用 terminal_value.py irr，解析其输出中的 IRR 百分数。"""
    out, _ = run_tool(TV_TOOL, "irr", "--profit", f"{profit:.6f}", "--mcap", f"{mcap:.6f}",
                      "--pe", f"{pe:.6f}", "--years", years, "--payout", f"{payout}")
    for line in out.splitlines():
        if "IRR" in line and "%" in line:
            token = line.split("%")[0].split()[-1]
            return D(token) / D(100), out   # 工具输出即为百分数，转回小数
    raise RuntimeError("无法解析 IRR 输出:\n" + out)


# ---------------------------------------------------------------- 计算
def main():
    calc = {}
    price = IN["price_HKD"]
    shares = IN["shares_100m"]
    fx = IN["fx_CNY_per_HKD"]

    mcap_hkd = price * shares
    mcap_cny = mcap_hkd * fx
    net_cash = IN["cash_equiv"] + IN["st_invest"] - IN["debt_incl_lease"]
    ev_total = mcap_cny - net_cash
    ev_core = ev_total - IN["strategic_invest_book"]

    calc["market"] = {
        "price_HKD": str(price), "shares_100m": str(shares), "fx_CNY_per_HKD": str(fx),
        "mcap_HKD_100m": f"{mcap_hkd:.6f}", "mcap_CNY_100m": f"{mcap_cny:.6f}",
        "net_cash_CNY_100m": f"{net_cash:.6f}",
        "ev_total_CNY_100m": f"{ev_total:.6f}",
        "ev_core_CNY_100m": f"{ev_core:.6f}",
        "price_per_share_CNY": f"{price / fx:.6f}",
    }

    # --- 十年终值与 IRR ---------------------------------------------------
    rows = {}
    for scen in ("bear", "base", "bull"):
        g = IN["g"][scen]
        roic, r = IN["roic"], IN["r"]
        pe = exit_pe(roic, g, r)
        profit = IN["profit_2036"][scen]
        cash = IN["cash_2036"][scen]
        inv = IN["invest_2036"][scen]
        # 终值市值 = 退出PE × 2036利润 + 期末盈余现金 + 战略投资变现价值
        tv = pe * profit + cash + inv
        # 工具口径：把现金与投资折成等值利润喂给 irr（profit' = profit + (cash+inv)/PE），
        # 结果与 (TV / mcap)^(1/10) - 1 完全等价，不是近似。
        profit_equiv = profit + (cash + inv) / pe
        irr, raw = irr_from_tool(profit_equiv, mcap_cny, pe, 10, IN["payout_base"])
        irr_dil, _ = irr_from_tool(profit_equiv, mcap_cny, pe, 10, IN["payout_dilution"])
        irr_check = (tv / mcap_cny) ** (D(1) / D(10)) - D(1)
        per_share_cny = tv / shares
        rows[scen] = {
            "g": str(g), "exit_pe": f"{pe:.6f}", "spread_pct": f"{(r - g) * 100:.2f}",
            "profit_2036": f"{profit:.6f}", "cash_2036": str(cash), "invest_2036": str(inv),
            "terminal_mcap_CNY_100m": f"{tv:.6f}",
            "per_share_CNY": f"{per_share_cny:.6f}",
            "per_share_HKD": f"{per_share_cny / fx:.6f}",
            "profit_equiv_for_tool": f"{profit_equiv:.6f}",
            "irr_10y_pct": f"{irr * 100:.4f}",
            "irr_10y_with_dilution_pct": f"{irr_dil * 100:.4f}",
            "irr_recomputed_pct": f"{irr_check * 100:.4f}",
            "irr_vs_price_pct": f"{((per_share_cny / fx) / price - 1) * 100:.4f}",
        }
        if scen == "base":
            rows[scen]["_raw_tool_output"] = raw
    calc["ten_year"] = rows

    # --- 反向 DCF：现价隐含什么 -------------------------------------------
    implied = {}
    for scen in ("bear", "base", "bull"):
        g = IN["g"][scen]
        pe = exit_pe(IN["roic"], g, IN["r"])
        tv_req = mcap_cny * (D(1) + IN["r"]) ** 10
        implied_profit = (tv_req - IN["cash_2036"][scen] - IN["invest_2036"][scen]) / pe
        # 反解核心收入 CAGR（保持该情景其余结构不变）
        other = (IN["new_biz_2036"][scen] + IN["hq_2036"][scen] + IN["finance_2036"][scen]
                 + IN["ai_pretax_2036"][scen])
        # 模型口径：税后 = (core_rev*margin + other) * (1 - 税率)
        # 故 core_rev*margin = 税后/(1-税率) - other
        rev_margin = implied_profit / (D(1) - IN["tax_rate"]) - other
        implied[scen] = {
            "exit_pe": f"{pe:.6f}",
            "tv_required_CNY_100m": f"{tv_req:.6f}",
            "implied_profit_2036": f"{implied_profit:.6f}",
            "implied_profit_vs_model_pct": f"{implied_profit / IN['profit_2036'][scen] * 100:.2f}",
            "implied_core_rev_x_margin": f"{rev_margin:.6f}",
        }
        # 情形一：核心利润率保持该情景假设，反解收入 CAGR
        margin = IN["core_margin_2036"][scen]
        implied_core_rev = rev_margin / margin
        cagr = (implied_core_rev / IN["core_rev_2026"]) ** (D(1) / D(10)) - D(1)
        implied[scen]["implied_core_rev_CAGR_pct"] = f"{cagr * 100:.4f}"
        implied[scen]["model_core_rev_CAGR_pct"] = f"{((IN['core_rev_2036'][scen] / IN['core_rev_2026']) ** (D(1) / D(10)) - D(1)) * 100:.4f}"
        # 情形二：核心收入保持该情景假设，反解利润率
        implied[scen]["implied_core_margin_pct"] = f"{rev_margin / IN['core_rev_2036'][scen] * 100:.4f}"
        implied[scen]["model_core_margin_pct"] = f"{margin * 100:.2f}"
    calc["reverse_dcf"] = implied

    # --- 三年情景（2029）--------------------------------------------------
    three = {}
    for scen in ("bear", "base", "bull"):
        pe = IN["pe_2029"][scen]
        profit = IN["profit_2029"][scen]
        cash = IN["cash_2029"][scen]
        inv = IN["invest_2029"][scen]
        if profit > 0:
            eq = (profit * pe + cash + inv) / shares
        else:
            # 亏损情景：盈利估值法失效，只计压力后盈余现金与折价投资
            eq = (cash + inv) / shares
        pv8 = eq / (D(1) + D("0.08")) ** 3
        pv10 = eq / (D(1) + D("0.10")) ** 3
        three[scen] = {
            "profit_2029": str(profit), "pe_2029": str(pe),
            "equity_value_CNY_100m": f"{(profit * pe + cash + inv) if profit > 0 else (cash + inv):.6f}",
            "per_share_HKD_2029": f"{eq / fx:.6f}",
            "pv_at_8pct_HKD": f"{pv8 / fx:.6f}",
            "pv_at_10pct_HKD": f"{pv10 / fx:.6f}",
            "cagr_to_2029_at_8pct_pct": f"{(((eq / fx) / price) ** (D(1) / D(3)) - D(1)) * 100:.4f}",
            "cagr_to_2029_at_10pct_pct": f"{(((eq / fx) / price) ** (D(1) / D(3)) - D(1)) * 100:.4f}",
        }
    calc["three_year"] = three

    # --- 敏感性：r / ROIC / 派息 ------------------------------------------
    sens = []
    for r_s in ("0.07", "0.08", "0.09", "0.10"):
        for roic_s in ("0.12", "0.15", "0.18"):
            g = IN["g"]["base"]
            pe = exit_pe(D(roic_s), g, D(r_s))
            if pe is None:
                continue
            profit = IN["profit_2036"]["base"]
            tv = pe * profit + IN["cash_2036"]["base"] + IN["invest_2036"]["base"]
            irr = (tv / mcap_cny) ** (D(1) / D(10)) - D(1)
            sens.append({"r": r_s, "roic": roic_s, "exit_pe": f"{pe:.4f}",
                         "spread_pct": f"{(D(r_s) - g) * 100:.2f}",
                         "irr_10y_pct": f"{irr * 100:.4f}",
                         "per_share_HKD": f"{(tv / shares) / fx:.4f}"})
    calc["sensitivity"] = sens

    # --- 路径依赖：十年 IRR 完全由 2036 年利润决定 -------------------------
    # 三年模型给出 2029 年利润，十年模型的 2036 年利润由此后七年决定。
    # 把这条腿单独拎出来做敏感性，是本报告最重要的单一变量。
    path = []
    pe_b = exit_pe(IN["roic"], IN["g"]["base"], IN["r"])
    for p36 in ("100", "150", "200", "252.1734848", "350", "450", "550",
                "673.95480284351865916620800", "900", "1100", "1398.63681883899537292012800"):
        p36d = D(p36)
        tv = pe_b * p36d + IN["cash_2036"]["base"] + IN["invest_2036"]["base"]
        irr = (tv / mcap_cny) ** (D(1) / D(10)) - D(1)
        cagr_29_36 = (p36d / IN["profit_2029"]["base"]) ** (D(1) / D(7)) - D(1)
        path.append({
            "profit_2036": p36,
            "cagr_2029_2036_pct": f"{cagr_29_36 * 100:.4f}",
            "terminal_mcap_CNY_100m": f"{tv:.6f}",
            "irr_10y_pct": f"{irr * 100:.4f}",
            "per_share_HKD_2036": f"{(tv / shares) / fx:.4f}",
        })
    calc["path_dependency_2036_profit"] = path

    # --- 汇率拖累：人民币口径 IRR 换算成港元投资者口径 -----------------------
    # 推导：投资者今日付 price 港元，2036 年得到 V_cny 人民币。
    #   fx_end = fx0 * (1+d)^10（人民币对港元年贬值 d）
    #   IRR_HKD = (V_cny/(fx0*(1+d)^10) / price)^(1/10) - 1
    #           = (1 + IRR_CNY) / (1 + d) - 1
    fx_rows = []
    for scen in ("bear", "base", "bull"):
        irr_cny = D(calc["ten_year"][scen]["irr_recomputed_pct"]) / D(100)
        for d in ("0", "0.01", "0.02", "0.03"):
            irr_hkd = (D(1) + irr_cny) / (D(1) + D(d)) - D(1)
            fx_rows.append({"scenario": scen, "rmb_dep_per_yr": d,
                            "irr_CNY_pct": f"{irr_cny * 100:.4f}",
                            "irr_HKD_pct": f"{irr_hkd * 100:.4f}"})
    calc["fx_drag"] = fx_rows

    # --- 价格 → 十年 IRR 对照（基准情景，用于给买入区间）-------------------
    pe_b = exit_pe(IN["roic"], IN["g"]["base"], IN["r"])
    tv_base = pe_b * IN["profit_2036"]["base"] + IN["cash_2036"]["base"] + IN["invest_2036"]["base"]
    price_rows = []
    for p in ("45", "50", "55", "60", "65", "70", "72.25", "76.10", "80", "85", "90"):
        pd_ = D(p)
        mcap_p = pd_ * shares * fx
        irr = (tv_base / mcap_p) ** (D(1) / D(10)) - D(1)
        irr_hkd2 = (D(1) + irr) / D("1.02") - D(1)
        pv3 = (IN["profit_2029"]["base"] * IN["pe_2029"]["base"]
               + IN["cash_2029"]["base"] + IN["invest_2029"]["base"]) / shares / fx
        cagr3 = ((pv3 / pd_) ** (D(1) / D(3)) - D(1)) * 100
        price_rows.append({
            "price_HKD": p,
            "mcap_CNY_100m": f"{mcap_p:.6f}",
            "irr_10y_CNY_pct": f"{irr * 100:.4f}",
            "irr_10y_HKD_2pct_fx_drag_pct": f"{irr_hkd2 * 100:.4f}",
            "cagr_3y_to_2029_pct": f"{cagr3:.4f}",
        })
    calc["price_to_irr"] = price_rows

    with open(os.path.join(HERE, "calculations.json"), "w", encoding="utf-8") as fh:
        json.dump(calc, fh, ensure_ascii=False, indent=2)
    print(json.dumps(calc, ensure_ascii=False, indent=2))

    # 工具留档
    for name, args in [
        ("terminal_value_pe_base.txt", ["pe", "--roic", "0.15", "--g", "0.02", "--r", "0.08"]),
        ("terminal_value_pe_bear.txt", ["pe", "--roic", "0.15", "--g", "0.01", "--r", "0.08"]),
        ("terminal_value_pe_bull.txt", ["pe", "--roic", "0.15", "--g", "0.03", "--r", "0.08"]),
    ]:
        out, _ = run_tool(TV_TOOL, *args)
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(out)

    # financial_rigor 市值验算留档
    out, _ = run_tool(FR_TOOL, "verify-market-cap", "--price", f"{price}",
                      "--shares", f"{shares * D('100000000')}", "--reported",
                      f"{mcap_hkd * D('100000000')}", "--currency", "HKD")
    with open(os.path.join(HERE, "financial_rigor_marketcap.txt"), "w", encoding="utf-8") as fh:
        fh.write(out)


if __name__ == "__main__":
    main()
