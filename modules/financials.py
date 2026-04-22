"""
modules/financials.py
Dedicated financial analysis backend for FinFlow.
All functions are self-contained and reusable across routes.
"""

import yfinance as yf


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def _safe(val, digits=2):
    try:
        return round(float(val), digits)
    except Exception:
        return None


def _fmt_cr(val):
    """Convert raw rupee value to Crores, rounded."""
    try:
        return round(float(val) / 1e7, 2)
    except Exception:
        return None


def _row(df, keys):
    """Extract first matching row from a DataFrame, return list of Crore values."""
    for k in keys:
        try:
            if df is not None and not df.empty and k in df.index:
                return [_fmt_cr(v) for v in df.loc[k]]
        except Exception:
            continue
    return []


def _scalar(df, keys):
    """Extract single scalar value (most recent column) from DataFrame."""
    for k in keys:
        try:
            if df is not None and not df.empty and k in df.index:
                return _fmt_cr(df.loc[k].iloc[0])
        except Exception:
            continue
    return None


def _years(df):
    if df is None or df.empty:
        return []
    return [str(c.year) if hasattr(c, 'year') else str(c)[:4] for c in df.columns]


# ─────────────────────────────────────────
#  CORE DATA FETCH
# ─────────────────────────────────────────

def get_full_financials(ticker: str) -> dict:
    """
    Master function. Returns everything needed for all analysis pages.
    Structure:
      info, balance_sheet, cash_flow, income_statement,
      ratios, scores, dcf_inputs, historical, years
    """
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info or {}
        fin   = stock.financials
        bs    = stock.balance_sheet
        cf    = stock.cashflow

        years = _years(fin)[:4]

        # ── Income Statement ──────────────────
        revenue    = _row(fin, ["Total Revenue"])[:4]
        net_income = _row(fin, ["Net Income"])[:4]
        gross_prof = _row(fin, ["Gross Profit"])[:4]
        ebitda     = _row(fin, ["EBITDA", "Normalized EBITDA"])[:4]
        op_income  = _row(fin, ["Operating Income", "Ebit"])[:4]
        interest   = _row(fin, ["Interest Expense"])[:4]
        tax        = _row(fin, ["Tax Provision", "Income Tax Expense"])[:4]

        # ── Balance Sheet ─────────────────────
        total_assets  = _row(bs, ["Total Assets"])[:4]
        curr_assets   = _row(bs, ["Total Current Assets", "Current Assets"])[:4]
        ncurr_assets  = [
            round(ta - ca, 2) if ta is not None and ca is not None else None
            for ta, ca in zip(_row(bs, ["Total Assets"])[:4],
                              _row(bs, ["Total Current Assets", "Current Assets"])[:4])
        ]
        curr_liab     = _row(bs, ["Total Current Liabilities", "Current Liabilities"])[:4]
        total_liab    = _row(bs, ["Total Liab", "Total Liabilities Net Minority Interest"])[:4]
        equity        = _row(bs, ["Total Stockholder Equity", "Stockholders Equity", "Total Equity"])[:4]
        total_debt    = _row(bs, ["Total Debt", "Long Term Debt"])[:4]
        cash          = _row(bs, ["Cash And Cash Equivalents", "Cash"])[:4]

        # ── Cash Flow ─────────────────────────
        op_cf  = _row(cf, ["Total Cash From Operating Activities", "Operating Cash Flow"])[:4]
        capex  = _row(cf, ["Capital Expenditures"])[:4]
        fcf_list = [
            round(o - abs(c), 2) if o is not None and c is not None else None
            for o, c in zip(op_cf, capex)
        ]

        # Most recent scalar values (for calculations)
        rev_0    = _scalar(fin, ["Total Revenue"])
        ni_0     = _scalar(fin, ["Net Income"])
        ca_0     = _scalar(bs,  ["Total Current Assets", "Current Assets"])
        cl_0     = _scalar(bs,  ["Total Current Liabilities", "Current Liabilities"])
        ta_0     = _scalar(bs,  ["Total Assets"])
        tl_0     = _scalar(bs,  ["Total Liab", "Total Liabilities Net Minority Interest"])
        eq_0     = _scalar(bs,  ["Total Stockholder Equity", "Stockholders Equity", "Total Equity"])
        td_0     = _scalar(bs,  ["Total Debt", "Long Term Debt"])
        ocf_0    = _scalar(cf,  ["Total Cash From Operating Activities", "Operating Cash Flow"])
        cap_0    = _scalar(cf,  ["Capital Expenditures"])
        fcf_0    = round(ocf_0 - abs(cap_0), 2) if ocf_0 and cap_0 else None
        cash_0   = _scalar(bs,  ["Cash And Cash Equivalents", "Cash"])

        # ── Ratios ────────────────────────────
        current_ratio  = round(ca_0 / cl_0, 2) if ca_0 and cl_0 else None
        de_ratio       = round(td_0 / eq_0, 2)  if td_0 and eq_0 else None
        net_margin     = round(ni_0 / rev_0 * 100, 2) if ni_0 and rev_0 else None
        roe            = _safe((info.get("returnOnEquity") or 0) * 100)
        roa            = _safe((info.get("returnOnAssets") or 0) * 100)
        pe             = _safe(info.get("trailingPE"))
        pb             = _safe(info.get("priceToBook"))
        eps            = _safe(info.get("trailingEps"))
        div_yield      = _safe((info.get("dividendYield") or 0) * 100)
        beta           = _safe(info.get("beta"))
        price          = _safe(info.get("currentPrice") or info.get("regularMarketPrice"), 2)

        ratios = {
            "current_ratio": current_ratio,
            "de_ratio":      de_ratio,
            "net_margin":    net_margin,
            "roe":           roe,
            "roa":           roa,
            "pe":            pe,
            "pb":            pb,
            "eps":           eps,
            "div_yield":     div_yield,
            "beta":          beta,
        }

        # ── Scoring (rule-based, out of 10) ──
        scores = _compute_scores(ratios, current_ratio, de_ratio, net_margin, roe, fcf_0)

        # ── Risk Flags ───────────────────────
        flags  = _compute_flags(current_ratio, de_ratio, net_margin, fcf_0,
                                 net_income, revenue)

        # ── Auto Insights ─────────────────────
        insights = _compute_insights(current_ratio, de_ratio, net_margin, roe, pe, pb, beta)

        # ── DCF Inputs ────────────────────────
        dcf_inputs = {
            "fcf":            fcf_0,
            "growth":         10.0,
            "discount":       12.0,
            "terminal_growth": 4.0,
        }

        # ── Company Info ─────────────────────
        company = {
            "name":        info.get("longName", ticker),
            "ticker":      ticker,
            "sector":      info.get("sector", "N/A"),
            "industry":    info.get("industry", "N/A"),
            "description": (info.get("longBusinessSummary") or "")[:600],
            "market_cap":  info.get("marketCap"),
            "price":       price,
            "high_52":     _safe(info.get("fiftyTwoWeekHigh")),
            "low_52":      _safe(info.get("fiftyTwoWeekLow")),
            "employees":   info.get("fullTimeEmployees"),
            "website":     info.get("website", ""),
        }

        return {
            "ok":      True,
            "company": company,
            "years":   years,
            "income": {
                "revenue":    revenue,
                "net_income": net_income,
                "gross_prof": gross_prof,
                "ebitda":     ebitda,
                "op_income":  op_income,
                "interest":   interest,
                "tax":        tax,
                # scalars
                "rev_0":  rev_0,
                "ni_0":   ni_0,
            },
            "balance": {
                "total_assets":  total_assets,
                "curr_assets":   curr_assets,
                "ncurr_assets":  ncurr_assets,
                "curr_liab":     curr_liab,
                "total_liab":    total_liab,
                "equity":        equity,
                "total_debt":    total_debt,
                "cash":          cash,
                # scalars
                "ca_0":  ca_0,
                "cl_0":  cl_0,
                "ta_0":  ta_0,
                "tl_0":  tl_0,
                "eq_0":  eq_0,
                "td_0":  td_0,
                "cash_0": cash_0,
            },
            "cashflow": {
                "op_cf":  op_cf,
                "capex":  capex,
                "fcf":    fcf_list,
                # scalars
                "ocf_0": ocf_0,
                "cap_0": cap_0,
                "fcf_0": fcf_0,
            },
            "ratios":    ratios,
            "scores":    scores,
            "flags":     flags,
            "insights":  insights,
            "dcf_inputs": dcf_inputs,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────
#  SCORING  (rule-based, /10 each)
# ─────────────────────────────────────────

def _compute_scores(ratios, current_ratio, de_ratio, net_margin, roe, fcf):
    def s(val, good, ok):
        if val is None: return 5
        if val >= good: return 9
        if val >= ok:   return 6
        return 3

    health = 5
    if current_ratio:
        health += 2 if current_ratio >= 2 else (1 if current_ratio >= 1.2 else -1)
    if de_ratio is not None:
        health += 2 if de_ratio < 0.5 else (1 if de_ratio < 1.5 else -2)
    if fcf is not None:
        health += 1 if fcf > 0 else -1
    health = max(1, min(10, health))

    profit = s(net_margin, 20, 10)
    if roe:
        profit = round((profit + s(roe, 20, 12)) / 2)

    risk = 10
    if de_ratio is not None:
        risk -= 0 if de_ratio < 0.5 else (2 if de_ratio < 1.5 else 4)
    if current_ratio:
        risk -= 0 if current_ratio >= 2 else (1 if current_ratio >= 1 else 3)
    if fcf is not None and fcf < 0:
        risk -= 2
    risk = max(1, min(10, int(risk)))

    valuation = 5
    pe = ratios.get("pe")
    pb = ratios.get("pb")
    if pe:
        valuation += 2 if pe < 15 else (1 if pe < 25 else -2)
    if pb:
        valuation += 1 if pb < 2 else (-1 if pb > 5 else 0)
    valuation = max(1, min(10, valuation))

    overall = round((health + profit + risk + valuation) / 4)
    return {
        "health":     int(health),
        "profit":     int(profit),
        "risk":       int(risk),
        "valuation":  int(valuation),
        "overall":    int(overall),
    }


# ─────────────────────────────────────────
#  RISK FLAGS
# ─────────────────────────────────────────

def _compute_flags(current_ratio, de_ratio, net_margin, fcf, net_income_list, revenue_list):
    flags = []
    if current_ratio and current_ratio < 1.0:
        flags.append({"type": "danger", "msg": "Current ratio below 1 — potential liquidity crisis"})
    elif current_ratio and current_ratio < 1.5:
        flags.append({"type": "warn", "msg": "Low current ratio — monitor short-term liquidity"})

    if de_ratio and de_ratio > 2:
        flags.append({"type": "danger", "msg": "High debt-to-equity (>2) — significant leverage risk"})
    elif de_ratio and de_ratio > 1:
        flags.append({"type": "warn", "msg": "Elevated debt-to-equity — moderate leverage"})

    if net_margin and net_margin < 0:
        flags.append({"type": "danger", "msg": "Negative net margin — company is unprofitable"})
    elif net_margin and net_margin < 5:
        flags.append({"type": "warn", "msg": "Low net margin (<5%) — thin profitability"})

    if fcf and fcf < 0:
        flags.append({"type": "warn", "msg": "Negative free cash flow — cash burn detected"})

    # Declining profit check
    if net_income_list and len(net_income_list) >= 2:
        valid = [x for x in net_income_list[:3] if x is not None]
        if len(valid) >= 2 and valid[0] < valid[1]:
            flags.append({"type": "warn", "msg": "Net income declining year-over-year"})

    if not flags:
        flags.append({"type": "ok", "msg": "No major red flags detected in key metrics"})

    return flags


# ─────────────────────────────────────────
#  AUTO INSIGHTS
# ─────────────────────────────────────────

def _compute_insights(current_ratio, de_ratio, net_margin, roe, pe, pb, beta):
    ins = []
    if current_ratio:
        if current_ratio >= 2:
            ins.append({"icon": "✅", "text": f"Strong liquidity (current ratio {current_ratio}x)"})
        elif current_ratio >= 1.2:
            ins.append({"icon": "🟡", "text": f"Adequate liquidity (current ratio {current_ratio}x)"})
        else:
            ins.append({"icon": "🔴", "text": f"Weak liquidity (current ratio {current_ratio}x)"})

    if de_ratio is not None:
        if de_ratio < 0.5:
            ins.append({"icon": "✅", "text": f"Very low leverage — debt/equity {de_ratio}x"})
        elif de_ratio < 1.5:
            ins.append({"icon": "🟡", "text": f"Moderate leverage — debt/equity {de_ratio}x"})
        else:
            ins.append({"icon": "🔴", "text": f"High leverage — debt/equity {de_ratio}x"})

    if net_margin:
        if net_margin >= 20:
            ins.append({"icon": "✅", "text": f"High profitability — net margin {net_margin}%"})
        elif net_margin >= 10:
            ins.append({"icon": "🟡", "text": f"Moderate profitability — net margin {net_margin}%"})
        elif net_margin > 0:
            ins.append({"icon": "🟡", "text": f"Low profit margin — {net_margin}% (room for improvement)"})
        else:
            ins.append({"icon": "🔴", "text": f"Negative margin — company is loss-making"})

    if roe:
        if roe >= 20:
            ins.append({"icon": "✅", "text": f"Excellent return on equity ({roe}%)"})
        elif roe >= 12:
            ins.append({"icon": "🟡", "text": f"Decent ROE ({roe}%)"})
        else:
            ins.append({"icon": "🔴", "text": f"Low ROE ({roe}%) — poor capital efficiency"})

    if pe:
        if pe < 15:
            ins.append({"icon": "✅", "text": f"Possibly undervalued — P/E of {pe}x"})
        elif pe < 30:
            ins.append({"icon": "🟡", "text": f"Fair valuation — P/E of {pe}x"})
        else:
            ins.append({"icon": "🔴", "text": f"Premium valuation — P/E of {pe}x"})

    if beta:
        if beta < 0.8:
            ins.append({"icon": "✅", "text": f"Defensive stock — beta {beta} (low market risk)"})
        elif beta > 1.5:
            ins.append({"icon": "🔴", "text": f"High volatility — beta {beta} (moves aggressively with market)"})

    return ins


# ─────────────────────────────────────────
#  DCF CALCULATION
# ─────────────────────────────────────────

def run_dcf(fcf, growth, discount, terminal_growth, years=5):
    """Returns dict with all DCF outputs."""
    try:
        fcf = float(fcf)
        growth = float(growth) / 100
        discount = float(discount) / 100
        tg = float(terminal_growth) / 100

        cash_flows     = []
        present_values = []
        cur = fcf
        for yr in range(1, years + 1):
            cur *= (1 + growth)
            pv = cur / ((1 + discount) ** yr)
            cash_flows.append(round(cur, 2))
            present_values.append(round(pv, 2))

        tv    = cash_flows[-1] * (1 + tg) / (discount - tg)
        tv_pv = tv / ((1 + discount) ** years)
        intrinsic = round(sum(present_values) + tv_pv, 2)

        return {
            "ok":             True,
            "cash_flows":     cash_flows,
            "present_values": present_values,
            "terminal_value": round(tv, 2),
            "terminal_pv":    round(tv_pv, 2),
            "intrinsic":      intrinsic,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────
#  RESEARCH REPORT  (full synthesis)
# ─────────────────────────────────────────

def generate_research_report(ticker: str) -> dict:
    """
    Synthesises all financial data + DCF + scoring into a
    single research report dict consumed by research_report.html
    """
    data = get_full_financials(ticker)
    if not data["ok"]:
        return data

    # Run DCF with default params
    fcf = data["cashflow"]["fcf_0"]
    dcf = run_dcf(fcf, 10, 12, 4) if fcf else {"ok": False, "error": "FCF unavailable"}

    # Verdict
    scores  = data["scores"]
    overall = scores["overall"]
    price   = data["company"]["price"]

    if dcf.get("ok") and price:
        intrinsic = dcf["intrinsic"]
        upside = round((intrinsic - price) / price * 100, 1) if price else None
        if upside and upside > 20:
            verdict_tag   = "UNDERVALUED"
            verdict_color = "green"
            verdict_text  = (f"{data['company']['name']} appears undervalued with "
                             f"~{upside}% upside based on DCF. ")
        elif upside and upside < -20:
            verdict_tag   = "OVERVALUED"
            verdict_color = "red"
            verdict_text  = (f"{data['company']['name']} appears overvalued by "
                             f"~{abs(upside)}% relative to DCF intrinsic value. ")
        else:
            verdict_tag   = "FAIRLY VALUED"
            verdict_color = "amber"
            verdict_text  = (f"{data['company']['name']} appears fairly valued near "
                             f"intrinsic DCF estimate. ")
    else:
        upside        = None
        verdict_tag   = "INCONCLUSIVE"
        verdict_color = "muted"
        verdict_text  = "Insufficient data for a complete DCF valuation. "

    if overall >= 8:
        verdict_text += "Fundamentals look strong overall."
    elif overall >= 6:
        verdict_text += "Fundamentals are mixed — requires further due diligence."
    else:
        verdict_text += "Multiple financial red flags detected — proceed with caution."

    # WACC (simplified)
    wacc = _estimate_wacc(data)

    data["dcf"]          = dcf
    data["wacc"]         = wacc
    data["verdict"]      = {
        "tag":   verdict_tag,
        "color": verdict_color,
        "text":  verdict_text,
        "upside": upside,
    }
    return data


def _estimate_wacc(data):
    """Rough WACC = Ke * E/(D+E) + Kd*(1-t) * D/(D+E)"""
    try:
        td  = data["balance"]["td_0"] or 0
        eq  = data["balance"]["eq_0"] or 1
        beta = data["ratios"]["beta"] or 1
        rfr  = 7.0    # India 10yr govt bond approx %
        mrp  = 5.5    # market risk premium %
        ke   = rfr + beta * mrp          # CAPM cost of equity %
        kd   = 8.0                        # assumed cost of debt %
        tax_rate = 25.0
        total = td + eq
        wacc = (ke * eq / total) + (kd * (1 - tax_rate/100) * td / total)
        return {"ke": round(ke, 2), "kd": kd, "wacc": round(wacc, 2),
                "tax_rate": tax_rate, "ok": True}
    except Exception:
        return {"ok": False}


# ─────────────────────────────────────────
#  COMPARISON
# ─────────────────────────────────────────

def compare_stocks(ticker1: str, ticker2: str) -> dict:
    """Returns side-by-side comparison of two tickers."""
    d1 = get_full_financials(ticker1)
    d2 = get_full_financials(ticker2)
    return {"t1": d1, "t2": d2,
            "ticker1": ticker1, "ticker2": ticker2}
