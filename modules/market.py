"""
modules/market.py
Compatible with yfinance >= 1.0.0
Key changes from 0.2.x:
  - stock.info now requires a network call, may be slow
  - Use fast_info for price/basic data where possible
  - history() API unchanged
  - financials/balance_sheet/cashflow unchanged
"""

import yfinance as yf
from datetime import datetime


# ================================================================
#  HELPERS
# ================================================================

def format_number(num):
    if not num:
        return "N/A"
    try:
        num = float(num)
    except Exception:
        return "N/A"
    if num >= 1e12:
        return f"₹{round(num / 1e12, 2)}T"
    elif num >= 1e9:
        return f"₹{round(num / 1e9, 2)}B"
    elif num >= 1e7:
        return f"₹{round(num / 1e7, 2)}Cr"
    elif num >= 1e5:
        return f"₹{round(num / 1e5, 2)}L"
    return f"₹{round(num, 2)}"


def safe_round(val, digits=2):
    try:
        return round(float(val), digits)
    except Exception:
        return "N/A"


def _safe_get(d, *keys, default=None):
    """Safely get from dict with multiple fallback keys."""
    for k in keys:
        try:
            v = d.get(k)
            if v is not None and v != "":
                return v
        except Exception:
            continue
    return default


def _fetch_change(ticker_sym):
    """Return (price, change, percent, direction) using history."""
    try:
        t = yf.Ticker(ticker_sym)
        hist = t.history(period="2d")
        if hist.empty or len(hist) < 2:
            hist = t.history(period="5d")
        if hist.empty:
            return 0.0, 0.0, 0.0, "flat"
        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        change = round(price - prev, 2)
        percent = round((change / prev) * 100, 2) if prev else 0.0
        return round(price, 2), change, percent, "up" if change >= 0 else "down"
    except Exception:
        return 0.0, 0.0, 0.0, "flat"


def _get_price_from_hist(ticker_sym):
    """Fast price lookup using only history — avoids slow info call."""
    try:
        hist = yf.Ticker(ticker_sym).history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return 0.0
    except Exception:
        return 0.0


# ================================================================
#  WATCHLIST DATA
# ================================================================

def get_watchlist_data(tickers):
    data_list = []
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo")
            if hist.empty:
                continue
            prices = list(hist["Close"].round(2))
            change = prices[-1] - prices[0]
            percent = (change / prices[0]) * 100 if prices[0] else 0

            # Get name safely
            try:
                name = stock.info.get("shortName") or stock.info.get("longName") or ticker
            except Exception:
                name = ticker

            data_list.append({
                "ticker": ticker,
                "name": name,
                "price": round(float(prices[-1]), 2),
                "change": round(change, 2),
                "percent": round(percent, 2),
                "chart": [round(float(p), 2) for p in prices[-10:]],
            })
        except Exception:
            continue
    return data_list


# ================================================================
#  STOCK DATA
# ================================================================

def get_stock_data(ticker, period="1y"):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)

        if hist.empty:
            return None

        # Use fast_info first (lightweight), fall back to info
        try:
            fi = stock.fast_info
            price = round(float(fi.last_price or 0), 2)
            prev_close = round(float(fi.previous_close or 0), 2)
            market_cap = fi.market_cap
        except Exception:
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev_close = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            market_cap = None

        # Full info for fundamentals (cached by yfinance)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        volumes = [int(v) for v in hist["Volume"].tolist()] if not hist.empty else []

        return {
            "ticker": ticker,
            "name": _safe_get(info, "longName", "shortName", default=ticker),
            "price": price or round(float(hist["Close"].iloc[-1]), 2),
            "prev_close": prev_close,
            "open": round(float(_safe_get(info, "regularMarketOpen", "open", default=0) or 0), 2),
            "day_high": round(float(_safe_get(info, "dayHigh", "regularMarketDayHigh", default=0) or 0), 2),
            "day_low": round(float(_safe_get(info, "dayLow", "regularMarketDayLow", default=0) or 0), 2),
            "market_cap": format_number(market_cap or _safe_get(info, "marketCap")),
            "pe_ratio": safe_round(_safe_get(info, "trailingPE", "forwardPE")),
            "pb_ratio": safe_round(_safe_get(info, "priceToBook")),
            "eps": safe_round(_safe_get(info, "trailingEps")),
            "roe": safe_round((_safe_get(info, "returnOnEquity") or 0) * 100),
            "debt_equity": safe_round(_safe_get(info, "debtToEquity")),
            "div_yield": safe_round((_safe_get(info, "dividendYield") or 0) * 100),
            "book_value": safe_round(_safe_get(info, "bookValue")),
            "high_52": safe_round(_safe_get(info, "fiftyTwoWeekHigh")),
            "low_52": safe_round(_safe_get(info, "fiftyTwoWeekLow")),
            "volume": _safe_get(info, "volume", "regularMarketVolume", default="N/A"),
            "avg_volume": _safe_get(info, "averageVolume", default="N/A"),
            "sector": _safe_get(info, "sector", default="N/A"),
            "industry": _safe_get(info, "industry", default="N/A"),
            "beta": safe_round(_safe_get(info, "beta")),
            "description": (_safe_get(info, "longBusinessSummary") or "")[:500],
            "chart_labels": list(hist.index.strftime("%Y-%m-%d")) if not hist.empty else [],
            "chart_data": [round(float(v), 2) for v in hist["Close"].tolist()] if not hist.empty else [],
            "chart_volume": volumes,
            "chart_high": [round(float(v), 2) for v in hist["High"].tolist()] if not hist.empty else [],
            "chart_low": [round(float(v), 2) for v in hist["Low"].tolist()] if not hist.empty else [],
        }
    except Exception as e:
        print(f"[get_stock_data] {ticker}: {e}")
        return None


# ================================================================
#  STOCK FINANCIALS  (for stock detail tabs)
# ================================================================

def get_stock_financials(ticker):
    try:
        stock = yf.Ticker(ticker)
        # yfinance 1.x: use income_stmt / balance_sheet / cashflow
        try:
            fin = stock.income_stmt
        except Exception:
            fin = stock.financials

        try:
            bs = stock.balance_sheet
        except Exception:
            bs = stock.balance_sheet

        try:
            cf = stock.cashflow
        except Exception:
            cf = stock.cashflow

        def row(df, keys):
            for k in keys:
                try:
                    if df is not None and not df.empty and k in df.index:
                        return [round(float(v) / 1e7, 2) for v in df.loc[k]]
                except Exception:
                    continue
            return []

        revenue = row(fin, ["Total Revenue"])
        net_income = row(fin, ["Net Income"])
        ebitda = row(fin, ["EBITDA", "Normalized EBITDA", "Reconciled Ebitda"])
        op_cf = row(cf, ["Total Cash From Operating Activities",
                         "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
        total_debt = row(bs, ["Total Debt", "Long Term Debt"])
        equity = row(bs, ["Total Stockholder Equity", "Stockholders Equity",
                          "Total Equity", "Stockholders Equity"])

        years = []
        if fin is not None and not fin.empty:
            years = [str(c.year) if hasattr(c, "year") else str(c)[:4]
                     for c in fin.columns]

        return {
            "years": years[:4],
            "revenue": revenue[:4],
            "net_income": net_income[:4],
            "ebitda": ebitda[:4],
            "op_cf": op_cf[:4],
            "total_debt": total_debt[:4],
            "equity": equity[:4],
        }
    except Exception as e:
        print(f"[get_stock_financials] {ticker}: {e}")
        return {}


# ================================================================
#  TRENDING
# ================================================================

def get_trending_stocks():
    tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
    result = []
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="1mo")
            if hist.empty or len(hist) < 2:
                continue
            prices = [round(float(v), 2) for v in hist["Close"].tolist()]
            start = prices[0]
            end = prices[-1]
            change = end - start
            percent = (change / start) * 100 if start else 0

            # Get name
            try:
                name = yf.Ticker(t).fast_info.get("longName") or t.replace(".NS", "")
            except Exception:
                name = t.replace(".NS", "")

            result.append({
                "ticker": t,
                "name": name,
                "price": end,
                "change": round(change, 2),
                "percent": round(percent, 2),
                "mini_chart": prices[-10:],
            })
        except Exception as e:
            print(f"[trending] {t}: {e}")
            continue
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
                "ticker": t,
                "display": t.replace(".NS", ""),
                "price": price,
                "change": change,
                "percent": percent,
                "direction": direction,
            })
    gainers = sorted(stocks, key=lambda x: x["percent"], reverse=True)[:5]
    losers = sorted(stocks, key=lambda x: x["percent"])[:5]
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
            hist = yf.Ticker(t).history(period="5d")
            if hist.empty:
                continue
            volume = int(hist["Volume"].mean())
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            change = round(price - prev, 2)
            percent = round((change / prev) * 100, 2) if prev else 0
            stocks.append({
                "ticker": t,
                "display": t.replace(".NS", ""),
                "price": price,
                "change": change,
                "percent": percent,
                "volume": volume,
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
    lows = []
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="1y")
            if hist.empty:
                continue
            price = round(float(hist["Close"].iloc[-1]), 2)
            high_52 = round(float(hist["High"].max()), 2)
            low_52 = round(float(hist["Low"].min()), 2)
            highs.append({"ticker": t, "display": t.replace(".NS", ""), "price": price, "high": high_52})
            lows.append({"ticker": t, "display": t.replace(".NS", ""), "price": price, "low": low_52})
        except Exception:
            continue
    return highs[:5], lows[:5]


# ================================================================
#  MARKET INDICES
# ================================================================

def get_indices_data():
    indices = [
        {"symbol": "^NSEI", "label": "NIFTY 50"},
        {"symbol": "^BSESN", "label": "SENSEX"},
    ]
    result = []
    for idx in indices:
        price, change, percent, direction = _fetch_change(idx["symbol"])
        result.append({
            "name": idx["label"],
            "symbol": idx["symbol"],
            "price": price,
            "change": change,
            "percent": percent,
            "direction": direction,
        })
    return result


# ================================================================
#  SECTOR INDICES
# ================================================================

def get_sector_data():
    sectors = [
        {"symbol": "^NSEBANK", "label": "Bank"},
        {"symbol": "^CNXIT", "label": "IT"},
        {"symbol": "^CNXPHARMA", "label": "Pharma"},
        {"symbol": "^CNXAUTO", "label": "Auto"},
        {"symbol": "^CNXFMCG", "label": "FMCG"},
        {"symbol": "^CNXMETAL", "label": "Metal"},
        {"symbol": "^CNXREALTY", "label": "Realty"},
        {"symbol": "^CNXENERGY", "label": "Energy"},
    ]
    result = []
    for s in sectors:
        price, change, percent, direction = _fetch_change(s["symbol"])
        result.append({
            "label": s["label"],
            "symbol": s["symbol"],
            "price": price,
            "change": change,
            "percent": percent,
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
                "ticker": t,
                "display": t.replace(".NS", ""),
                "price": price,
                "change": change,
                "percent": percent,
                "direction": direction,
            })
    return result


# ================================================================
#  TODAY'S STOCKS
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
            hist = yf.Ticker(t).history(period="5d")
            if hist.empty:
                continue
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            change = round(price - prev, 2)
            percent = round((change / prev) * 100, 2) if prev else 0
            volume = int(hist["Volume"].mean())
            high_52 = round(float(hist["High"].max()), 2)
            low_52 = round(float(hist["Low"].min()), 2)

            # Name: try fast_info first
            try:
                name = t.replace(".NS", "")
            except Exception:
                name = t.replace(".NS", "")

            rows.append({
                "ticker": t,
                "display": t.replace(".NS", ""),
                "name": name,
                "price": price,
                "change": change,
                "percent": percent,
                "direction": "up" if change >= 0 else "down",
                "volume": volume,
                "high_52": high_52,
                "low_52": low_52,
            })
        except Exception as e:
            print(f"[todays_stocks] {t}: {e}")
            continue

    return {
        "gainers": sorted(rows, key=lambda x: x["percent"], reverse=True)[:8],
        "losers": sorted(rows, key=lambda x: x["percent"])[:8],
        "active": sorted(rows, key=lambda x: x["volume"], reverse=True)[:8],
        "highs": sorted(rows, key=lambda x: (
            x["price"] / x["high_52"]
            if isinstance(x["high_52"], float) and x["high_52"] else 0
        ), reverse=True)[:8],
        "lows": sorted(rows, key=lambda x: (
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
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "total": total,
        "advance_pct": round(advances / total * 100),
        "decline_pct": round(declines / total * 100),
        "unchanged_pct": round(unchanged / total * 100),
    }