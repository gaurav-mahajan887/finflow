import yfinance as yf
from datetime import datetime


# ================================================================
#  HELPERS
# ================================================================

def format_number(num):
    if not num:
        return "N/A"
    if num >= 1e12:
        return f"₹{round(num/1e12, 2)}T"
    elif num >= 1e9:
        return f"₹{round(num/1e9, 2)}B"
    elif num >= 1e7:
        return f"₹{round(num/1e7, 2)}Cr"
    elif num >= 1e5:
        return f"₹{round(num/1e5, 2)}L"
    return f"₹{round(num, 2)}"


def safe_round(val, digits=2):
    try:
        return round(float(val), digits)
    except Exception:
        return "N/A"


def _fetch_change(ticker_sym):
    """Return (price, change, percent, direction) for a symbol."""
    try:
        t    = yf.Ticker(ticker_sym)
        hist = t.history(period="2d")
        if hist.empty or len(hist) < 2:
            info  = t.info
            price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0)
            prev  = float(info.get("regularMarketPreviousClose") or price)
        else:
            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
        change  = round(price - prev, 2)
        percent = round((change / prev) * 100, 2) if prev else 0.0
        return round(price, 2), change, percent, "up" if change >= 0 else "down"
    except Exception:
        return 0.0, 0.0, 0.0, "flat"


# ================================================================
#  WATCHLIST DATA
# ================================================================

def get_watchlist_data(tickers):
    data_list = []
    for ticker in tickers:
        try:
            stock  = yf.Ticker(ticker)
            info   = stock.info
            hist   = stock.history(period="1mo")
            if hist.empty:
                continue
            prices  = list(hist["Close"].round(2))
            change  = prices[-1] - prices[0]
            percent = (change / prices[0]) * 100 if prices[0] else 0
            data_list.append({
                "ticker":  ticker,
                "name":    info.get("shortName", ticker),
                "price":   round(info.get("currentPrice", 0), 2),
                "change":  round(change, 2),
                "percent": round(percent, 2),
                "chart":   prices[-10:]
            })
        except Exception:
            continue
    return data_list


# ================================================================
#  STOCK DATA  (enhanced with extra fundamental fields)
# ================================================================

def get_stock_data(ticker, period="1y"):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        hist  = stock.history(period=period)

        volumes = [int(v) for v in hist["Volume"].tolist()] if not hist.empty else []

        return {
            "ticker":      ticker,
            "name":        info.get("longName", ticker),
            "price":       round(info.get("currentPrice", 0), 2),
            "prev_close":  round(info.get("regularMarketPreviousClose", 0), 2),
            "open":        round(info.get("regularMarketOpen", 0), 2),
            "day_high":    round(info.get("dayHigh", 0), 2),
            "day_low":     round(info.get("dayLow", 0), 2),
            "market_cap":  format_number(info.get("marketCap")),
            "pe_ratio":    safe_round(info.get("trailingPE")),
            "pb_ratio":    safe_round(info.get("priceToBook")),
            "eps":         safe_round(info.get("trailingEps")),
            "roe":         safe_round((info.get("returnOnEquity") or 0) * 100),
            "debt_equity": safe_round(info.get("debtToEquity")),
            "div_yield":   safe_round((info.get("dividendYield") or 0) * 100),
            "book_value":  safe_round(info.get("bookValue")),
            "high_52":     safe_round(info.get("fiftyTwoWeekHigh")),
            "low_52":      safe_round(info.get("fiftyTwoWeekLow")),
            "volume":      info.get("volume", "N/A"),
            "avg_volume":  info.get("averageVolume", "N/A"),
            "sector":      info.get("sector", "N/A"),
            "industry":    info.get("industry", "N/A"),
            "beta":        safe_round(info.get("beta")),
            "description": (info.get("longBusinessSummary", "") or "")[:500],
            "chart_labels": list(hist.index.strftime("%Y-%m-%d")) if not hist.empty else [],
            "chart_data":   list(hist["Close"].round(2)) if not hist.empty else [],
            "chart_volume": volumes,
            "chart_high":   list(hist["High"].round(2)) if not hist.empty else [],
            "chart_low":    list(hist["Low"].round(2)) if not hist.empty else [],
        }
    except Exception:
        return None


# ================================================================
#  STOCK FINANCIALS  (for detail page tabs)
# ================================================================

def get_stock_financials(ticker):
    try:
        stock = yf.Ticker(ticker)
        fin   = stock.financials
        bs    = stock.balance_sheet
        cf    = stock.cashflow

        def row(df, keys):
            for k in keys:
                try:
                    if df is not None and not df.empty and k in df.index:
                        return [round(float(v) / 1e7, 2) for v in df.loc[k]]
                except Exception:
                    continue
            return []

        revenue    = row(fin, ["Total Revenue"])
        net_income = row(fin, ["Net Income"])
        ebitda     = row(fin, ["EBITDA", "Normalized EBITDA"])
        op_cf      = row(cf,  ["Total Cash From Operating Activities", "Operating Cash Flow"])
        total_debt = row(bs,  ["Total Debt", "Long Term Debt"])
        equity     = row(bs,  ["Total Stockholder Equity", "Stockholders Equity", "Total Equity"])

        years = []
        if fin is not None and not fin.empty:
            years = [str(c.year) if hasattr(c, "year") else str(c)[:4]
                     for c in fin.columns]

        return {
            "years":      years[:4],
            "revenue":    revenue[:4],
            "net_income": net_income[:4],
            "ebitda":     ebitda[:4],
            "op_cf":      op_cf[:4],
            "total_debt": total_debt[:4],
            "equity":     equity[:4],
        }
    except Exception:
        return {}


# ================================================================
#  TRENDING
# ================================================================

def get_trending_stocks():
    tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
    result  = []
    for t in tickers:
        data = get_stock_data(t, "1mo")
        if data and data["chart_data"]:
            start   = data["chart_data"][0]
            end     = data["chart_data"][-1]
            change  = end - start
            percent = (change / start) * 100 if start else 0
            result.append({
                "ticker":     t,
                "name":       data["name"],
                "price":      data["price"],
                "change":     round(change, 2),
                "percent":    round(percent, 2),
                "mini_chart": data["chart_data"][-10:]
            })
    return result


# ================================================================
#  GAINERS / LOSERS
# ================================================================

def get_gainers_losers():
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "SBIN.NS", "WIPRO.NS", "AXISBANK.NS",
        "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS",
    ]
    stocks = []
    for t in tickers:
        price, change, percent, direction = _fetch_change(t)
        if price:
            stocks.append({
                "ticker":    t,
                "display":   t.replace(".NS", ""),
                "price":     price,
                "change":    change,
                "percent":   percent,
                "direction": direction,
            })
    gainers = sorted(stocks, key=lambda x: x["percent"], reverse=True)[:5]
    losers  = sorted(stocks, key=lambda x: x["percent"])[:5]
    return gainers, losers


# ================================================================
#  MOST ACTIVE
# ================================================================

def get_most_active():
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "SBIN.NS", "WIPRO.NS", "AXISBANK.NS",
    ]
    stocks = []
    for t in tickers:
        try:
            stock  = yf.Ticker(t)
            hist   = stock.history(period="5d")
            volume = int(hist["Volume"].mean())
            price  = round(float(hist["Close"].iloc[-1]), 2)
            prev   = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            change  = round(price - prev, 2)
            percent = round((change / prev) * 100, 2) if prev else 0
            stocks.append({
                "ticker":    t,
                "display":   t.replace(".NS", ""),
                "price":     price,
                "change":    change,
                "percent":   percent,
                "volume":    volume,
                "direction": "up" if change >= 0 else "down",
            })
        except Exception:
            continue
    return sorted(stocks, key=lambda x: x["volume"], reverse=True)[:5]


# ================================================================
#  52-WEEK BREAKOUTS
# ================================================================

def get_52w_breakouts():
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "SBIN.NS", "WIPRO.NS", "AXISBANK.NS",
    ]
    highs = []
    lows  = []
    for t in tickers:
        data = get_stock_data(t)
        if data:
            highs.append({
                "ticker":  t,
                "display": t.replace(".NS", ""),
                "price":   data["price"],
                "high":    data["high_52"],
            })
            lows.append({
                "ticker":  t,
                "display": t.replace(".NS", ""),
                "price":   data["price"],
                "low":     data["low_52"],
            })
    return highs[:5], lows[:5]


# ================================================================
#  MARKET INDICES
# ================================================================

def get_indices_data():
    indices = [
        {"symbol": "^NSEI",  "label": "NIFTY 50"},
        {"symbol": "^BSESN", "label": "SENSEX"},
    ]
    result = []
    for idx in indices:
        price, change, percent, direction = _fetch_change(idx["symbol"])
        result.append({
            "name":      idx["label"],
            "symbol":    idx["symbol"],
            "price":     price,
            "change":    change,
            "percent":   percent,
            "direction": direction,
        })
    return result


# ================================================================
#  SECTOR INDICES
# ================================================================

def get_sector_data():
    sectors = [
        {"symbol": "^NSEBANK",   "label": "Bank"},
        {"symbol": "^CNXIT",     "label": "IT"},
        {"symbol": "^CNXPHARMA", "label": "Pharma"},
        {"symbol": "^CNXAUTO",   "label": "Auto"},
        {"symbol": "^CNXFMCG",   "label": "FMCG"},
        {"symbol": "^CNXMETAL",  "label": "Metal"},
        {"symbol": "^CNXREALTY", "label": "Realty"},
        {"symbol": "^CNXENERGY", "label": "Energy"},
    ]
    result = []
    for s in sectors:
        price, change, percent, direction = _fetch_change(s["symbol"])
        result.append({
            "label":     s["label"],
            "symbol":    s["symbol"],
            "price":     price,
            "change":    change,
            "percent":   percent,
            "direction": direction,
        })
    return result


# ================================================================
#  TICKER BAR
# ================================================================

def get_ticker_bar_stocks():
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "SBIN.NS", "WIPRO.NS", "AXISBANK.NS",
        "LT.NS", "BAJFINANCE.NS",
    ]
    result = []
    for t in tickers:
        price, change, percent, direction = _fetch_change(t)
        if price:
            result.append({
                "ticker":    t,
                "display":   t.replace(".NS", ""),
                "price":     price,
                "change":    change,
                "percent":   percent,
                "direction": direction,
            })
    return result


# ================================================================
#  TODAY'S STOCKS  (all categories for the tabbed panel)
# ================================================================

def get_todays_stocks():
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "SBIN.NS", "WIPRO.NS", "AXISBANK.NS",
        "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS",
        "NTPC.NS", "POWERGRID.NS", "ONGC.NS", "COALINDIA.NS",
    ]
    rows = []
    for t in tickers:
        try:
            stock = yf.Ticker(t)
            info  = stock.info
            hist  = stock.history(period="5d")
            if hist.empty:
                continue
            price   = round(float(hist["Close"].iloc[-1]), 2)
            prev    = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            change  = round(price - prev, 2)
            percent = round((change / prev) * 100, 2) if prev else 0
            volume  = int(hist["Volume"].mean())
            h52     = safe_round(info.get("fiftyTwoWeekHigh"))
            l52     = safe_round(info.get("fiftyTwoWeekLow"))
            name    = info.get("shortName", t.replace(".NS", ""))
            rows.append({
                "ticker":    t,
                "display":   t.replace(".NS", ""),
                "name":      name,
                "price":     price,
                "change":    change,
                "percent":   percent,
                "direction": "up" if change >= 0 else "down",
                "volume":    volume,
                "high_52":   h52,
                "low_52":    l52,
            })
        except Exception:
            continue

    return {
        "gainers": sorted(rows, key=lambda x: x["percent"], reverse=True)[:8],
        "losers":  sorted(rows, key=lambda x: x["percent"])[:8],
        "active":  sorted(rows, key=lambda x: x["volume"],  reverse=True)[:8],
        "highs":   sorted(rows, key=lambda x: (
                       x["price"] / x["high_52"]
                       if isinstance(x["high_52"], float) and x["high_52"] else 0
                   ), reverse=True)[:8],
        "lows":    sorted(rows, key=lambda x: (
                       x["price"] / x["low_52"]
                       if isinstance(x["low_52"], float) and x["low_52"] else 999
                   ))[:8],
    }


# ================================================================
#  MARKET BREADTH
# ================================================================

def get_market_breadth():
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "SBIN.NS", "WIPRO.NS", "AXISBANK.NS",
        "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS",
        "NTPC.NS", "POWERGRID.NS", "ONGC.NS", "COALINDIA.NS",
        "TATAMOTORS.NS", "TATASTEEL.NS", "SUNPHARMA.NS", "ASIANPAINT.NS",
    ]
    advances = declines = unchanged = 0
    for t in tickers:
        _, change, _, _ = _fetch_change(t)
        if change > 0:
            advances += 1
        elif change < 0:
            declines += 1
        else:
            unchanged += 1
    total = advances + declines + unchanged or 1
    return {
        "advances":      advances,
        "declines":      declines,
        "unchanged":     unchanged,
        "total":         total,
        "advance_pct":   round(advances  / total * 100),
        "decline_pct":   round(declines  / total * 100),
        "unchanged_pct": round(unchanged / total * 100),
    }
