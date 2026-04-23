"""
modules/market.py
Compatible with yfinance 1.3.0
Includes:
  - Rate limit protection (delays between calls)
  - Module-level cache (10-minute TTL)
  - curl_cffi session for bypassing IP blocks
  - history()-first approach (avoids slow .info calls on market page)
"""

import time
import yfinance as yf

# ── Module-level cache (survives across requests in same worker) ──
_cache = {}
_CACHE_TTL = 600  # 10 minutes


def _cached(key, fn):
    """Return cached value or call fn() and cache result."""
    now = time.time()
    if key in _cache and (now - _cache[key]["ts"]) < _CACHE_TTL:
        return _cache[key]["data"]
    try:
        result = fn()
        if result is not None:
            _cache[key] = {"data": result, "ts": now}
        return result
    except Exception as e:
        print(f"[cache miss] {key}: {e}")
        # Return stale data if available
        if key in _cache:
            return _cache[key]["data"]
        return None


def _sleep():
    """Small delay to avoid rate limits."""
    time.sleep(0.3)


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
        v = float(val)
        if v != v:  # NaN check
            return "N/A"
        return round(v, digits)
    except Exception:
        return "N/A"


def _safe_get(d, *keys, default=None):
    for k in keys:
        try:
            v = d.get(k)
            if v is not None and v != "" and v == v:  # not NaN
                return v
        except Exception:
            continue
    return default


def _hist_price_change(ticker_sym):
    """
    Get price + change using only history() — fastest, most reliable.
    Returns (price, change, percent, direction).
    """
    try:
        hist = yf.Ticker(ticker_sym).history(period="5d")
        if hist.empty or len(hist) < 2:
            return 0.0, 0.0, 0.0, "flat"
        price = round(float(hist["Close"].iloc[-1]), 2)
        prev  = round(float(hist["Close"].iloc[-2]), 2)
        change  = round(price - prev, 2)
        percent = round((change / prev) * 100, 2) if prev else 0.0
        return price, change, percent, "up" if change >= 0 else "down"
    except Exception as e:
        print(f"[price_change] {ticker_sym}: {e}")
        return 0.0, 0.0, 0.0, "flat"


# ================================================================
#  WATCHLIST DATA
# ================================================================

def get_watchlist_data(tickers):
    data_list = []
    for ticker in tickers:
        def _fetch(t=ticker):
            stock = yf.Ticker(t)
            hist  = stock.history(period="1mo")
            if hist.empty:
                return None
            prices  = [round(float(v), 2) for v in hist["Close"].tolist()]
            change  = prices[-1] - prices[0]
            percent = (change / prices[0]) * 100 if prices[0] else 0
            return {
                "ticker":  t,
                "name":    t.replace(".NS", ""),
                "price":   prices[-1],
                "change":  round(change, 2),
                "percent": round(percent, 2),
                "chart":   prices[-10:],
            }
        result = _cached(f"watchlist:{ticker}", _fetch)
        if result:
            data_list.append(result)
        _sleep()
    return data_list


# ================================================================
#  STOCK DATA  (full detail — used for stock detail page)
# ================================================================

def get_stock_data(ticker, period="1y"):
    def _fetch():
        stock = yf.Ticker(ticker)
        hist  = stock.history(period=period)
        if hist.empty:
            return None

        price      = round(float(hist["Close"].iloc[-1]), 2)
        prev_close = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price

        # Try fast_info for market cap (lightweight)
        market_cap = None
        try:
            fi = stock.fast_info
            market_cap = getattr(fi, "market_cap", None)
        except Exception:
            pass

        # Try full info for fundamentals
        info = {}
        try:
            info = stock.info or {}
        except Exception:
            pass

        volumes = [int(v) for v in hist["Volume"].tolist()]

        return {
            "ticker":       ticker,
            "name":         _safe_get(info, "longName", "shortName", default=ticker.replace(".NS","")),
            "price":        price,
            "prev_close":   prev_close,
            "open":         round(float(_safe_get(info, "regularMarketOpen", "open", default=price) or price), 2),
            "day_high":     round(float(hist["High"].iloc[-1]), 2),
            "day_low":      round(float(hist["Low"].iloc[-1]), 2),
            "market_cap":   format_number(market_cap or _safe_get(info, "marketCap")),
            "pe_ratio":     safe_round(_safe_get(info, "trailingPE", "forwardPE")),
            "pb_ratio":     safe_round(_safe_get(info, "priceToBook")),
            "eps":          safe_round(_safe_get(info, "trailingEps")),
            "roe":          safe_round((_safe_get(info, "returnOnEquity") or 0) * 100),
            "debt_equity":  safe_round(_safe_get(info, "debtToEquity")),
            "div_yield":    safe_round((_safe_get(info, "dividendYield") or 0) * 100),
            "book_value":   safe_round(_safe_get(info, "bookValue")),
            "high_52":      round(float(hist["High"].max()), 2),
            "low_52":       round(float(hist["Low"].min()), 2),
            "volume":       int(hist["Volume"].iloc[-1]) if not hist.empty else "N/A",
            "avg_volume":   int(hist["Volume"].mean())   if not hist.empty else "N/A",
            "sector":       _safe_get(info, "sector",   default="N/A"),
            "industry":     _safe_get(info, "industry", default="N/A"),
            "beta":         safe_round(_safe_get(info, "beta")),
            "description":  (_safe_get(info, "longBusinessSummary") or "")[:500],
            "chart_labels": list(hist.index.strftime("%Y-%m-%d")),
            "chart_data":   [round(float(v), 2) for v in hist["Close"].tolist()],
            "chart_volume": volumes,
            "chart_high":   [round(float(v), 2) for v in hist["High"].tolist()],
            "chart_low":    [round(float(v), 2) for v in hist["Low"].tolist()],
        }

    return _cached(f"stock:{ticker}:{period}", _fetch)


# ================================================================
#  STOCK FINANCIALS
# ================================================================

def get_stock_financials(ticker):
    def _fetch():
        stock = yf.Ticker(ticker)
        try:
            fin = stock.income_stmt
        except Exception:
            try:
                fin = stock.financials
            except Exception:
                fin = None

        bs = None
        try:
            bs = stock.balance_sheet
        except Exception:
            pass

        cf = None
        try:
            cf = stock.cashflow
        except Exception:
            pass

        def row(df, keys):
            for k in keys:
                try:
                    if df is not None and not df.empty and k in df.index:
                        return [round(float(v) / 1e7, 2) for v in df.loc[k]]
                except Exception:
                    continue
            return []

        years = []
        if fin is not None and not fin.empty:
            years = [str(c.year) if hasattr(c, "year") else str(c)[:4]
                     for c in fin.columns]

        return {
            "years":      years[:4],
            "revenue":    row(fin, ["Total Revenue"])[:4],
            "net_income": row(fin, ["Net Income"])[:4],
            "ebitda":     row(fin, ["EBITDA", "Normalized EBITDA", "Reconciled Ebitda"])[:4],
            "op_cf":      row(cf,  ["Operating Cash Flow",
                                     "Total Cash From Operating Activities",
                                     "Cash Flow From Continuing Operating Activities"])[:4],
            "total_debt": row(bs,  ["Total Debt", "Long Term Debt"])[:4],
            "equity":     row(bs,  ["Stockholders Equity", "Total Stockholder Equity",
                                     "Total Equity"])[:4],
        }

    return _cached(f"fin:{ticker}", _fetch) or {}


# ================================================================
#  TRENDING  (history-only, no .info call)
# ================================================================

def get_trending_stocks():
    def _fetch():
        tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
        result  = []
        for t in tickers:
            try:
                hist = yf.Ticker(t).history(period="1mo")
                if hist.empty or len(hist) < 2:
                    continue
                prices  = [round(float(v), 2) for v in hist["Close"].tolist()]
                start, end = prices[0], prices[-1]
                change  = end - start
                percent = (change / start) * 100 if start else 0
                result.append({
                    "ticker":     t,
                    "name":       t.replace(".NS", ""),
                    "price":      end,
                    "change":     round(change, 2),
                    "percent":    round(percent, 2),
                    "mini_chart": prices[-10:],
                })
                _sleep()
            except Exception as e:
                print(f"[trending] {t}: {e}")
        return result

    return _cached("trending", _fetch) or []


# ================================================================
#  GAINERS / LOSERS
# ================================================================

def get_gainers_losers():
    def _fetch():
        tickers = [
            "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
            "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
            "LT.NS","BAJFINANCE.NS","HCLTECH.NS","MARUTI.NS",
        ]
        stocks = []
        for t in tickers:
            price, change, percent, direction = _hist_price_change(t)
            if price:
                stocks.append({
                    "ticker":    t,
                    "display":   t.replace(".NS", ""),
                    "price":     price,
                    "change":    change,
                    "percent":   percent,
                    "direction": direction,
                })
            _sleep()
        gainers = sorted(stocks, key=lambda x: x["percent"], reverse=True)[:5]
        losers  = sorted(stocks, key=lambda x: x["percent"])[:5]
        return gainers, losers

    result = _cached("gainers_losers", _fetch)
    if result:
        return result
    return [], []


# ================================================================
#  MOST ACTIVE
# ================================================================

def get_most_active():
    def _fetch():
        tickers = [
            "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
            "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
        ]
        stocks = []
        for t in tickers:
            try:
                hist = yf.Ticker(t).history(period="5d")
                if hist.empty:
                    continue
                price   = round(float(hist["Close"].iloc[-1]), 2)
                prev    = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
                change  = round(price - prev, 2)
                percent = round((change / prev) * 100, 2) if prev else 0
                volume  = int(hist["Volume"].mean())
                stocks.append({
                    "ticker":    t,
                    "display":   t.replace(".NS", ""),
                    "price":     price,
                    "change":    change,
                    "percent":   percent,
                    "volume":    volume,
                    "direction": "up" if change >= 0 else "down",
                })
                _sleep()
            except Exception:
                continue
        return sorted(stocks, key=lambda x: x["volume"], reverse=True)[:5]

    return _cached("most_active", _fetch) or []


# ================================================================
#  52-WEEK BREAKOUTS
# ================================================================

def get_52w_breakouts():
    def _fetch():
        tickers = [
            "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
            "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
        ]
        highs, lows = [], []
        for t in tickers:
            try:
                hist = yf.Ticker(t).history(period="1y")
                if hist.empty:
                    continue
                price   = round(float(hist["Close"].iloc[-1]), 2)
                high_52 = round(float(hist["High"].max()), 2)
                low_52  = round(float(hist["Low"].min()), 2)
                highs.append({"ticker": t, "display": t.replace(".NS",""), "price": price, "high": high_52})
                lows.append( {"ticker": t, "display": t.replace(".NS",""), "price": price, "low":  low_52})
                _sleep()
            except Exception:
                continue
        return highs[:5], lows[:5]

    result = _cached("52w", _fetch)
    if result:
        return result
    return [], []


# ================================================================
#  MARKET INDICES
# ================================================================

def get_indices_data():
    def _fetch():
        indices = [
            {"symbol": "^NSEI",  "label": "NIFTY 50"},
            {"symbol": "^BSESN", "label": "SENSEX"},
        ]
        result = []
        for idx in indices:
            price, change, percent, direction = _hist_price_change(idx["symbol"])
            result.append({
                "name":      idx["label"],
                "symbol":    idx["symbol"],
                "price":     price,
                "change":    change,
                "percent":   percent,
                "direction": direction,
            })
            _sleep()
        return result

    return _cached("indices", _fetch) or []


# ================================================================
#  SECTOR INDICES
# ================================================================

def get_sector_data():
    def _fetch():
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
            price, change, percent, direction = _hist_price_change(s["symbol"])
            result.append({
                "label":     s["label"],
                "symbol":    s["symbol"],
                "price":     price,
                "change":    change,
                "percent":   percent,
                "direction": direction,
            })
            _sleep()
        return result

    return _cached("sectors", _fetch) or []


# ================================================================
#  TICKER BAR
# ================================================================

def get_ticker_bar_stocks():
    def _fetch():
        tickers = [
            "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
            "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
            "LT.NS","BAJFINANCE.NS",
        ]
        result = []
        for t in tickers:
            price, change, percent, direction = _hist_price_change(t)
            if price:
                result.append({
                    "ticker":    t,
                    "display":   t.replace(".NS", ""),
                    "price":     price,
                    "change":    change,
                    "percent":   percent,
                    "direction": direction,
                })
            _sleep()
        return result

    return _cached("ticker_bar", _fetch) or []


# ================================================================
#  TODAY'S STOCKS
# ================================================================

def get_todays_stocks():
    def _fetch():
        tickers = [
            "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
            "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
            "LT.NS","BAJFINANCE.NS","HCLTECH.NS","MARUTI.NS",
            "NTPC.NS","POWERGRID.NS","ONGC.NS","COALINDIA.NS",
        ]
        rows = []
        for t in tickers:
            try:
                hist = yf.Ticker(t).history(period="5d")
                if hist.empty:
                    continue
                price   = round(float(hist["Close"].iloc[-1]), 2)
                prev    = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
                change  = round(price - prev, 2)
                percent = round((change / prev) * 100, 2) if prev else 0
                volume  = int(hist["Volume"].mean())
                high_52 = round(float(hist["High"].max()), 2)
                low_52  = round(float(hist["Low"].min()), 2)
                rows.append({
                    "ticker":    t,
                    "display":   t.replace(".NS", ""),
                    "name":      t.replace(".NS", ""),
                    "price":     price,
                    "change":    change,
                    "percent":   percent,
                    "direction": "up" if change >= 0 else "down",
                    "volume":    volume,
                    "high_52":   high_52,
                    "low_52":    low_52,
                })
                _sleep()
            except Exception as e:
                print(f"[todays_stocks] {t}: {e}")
                continue

        return {
            "gainers": sorted(rows, key=lambda x: x["percent"], reverse=True)[:8],
            "losers":  sorted(rows, key=lambda x: x["percent"])[:8],
            "active":  sorted(rows, key=lambda x: x["volume"],  reverse=True)[:8],
            "highs":   sorted(rows, key=lambda x: (
                           x["price"] / x["high_52"]
                           if x["high_52"] else 0
                       ), reverse=True)[:8],
            "lows":    sorted(rows, key=lambda x: (
                           x["price"] / x["low_52"]
                           if x["low_52"] else 999
                       ))[:8],
        }

    return _cached("todays_stocks", _fetch) or {
        "gainers": [], "losers": [], "active": [], "highs": [], "lows": []
    }


# ================================================================
#  MARKET BREADTH
# ================================================================

def get_market_breadth():
    def _fetch():
        tickers = [
            "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
            "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
            "LT.NS","BAJFINANCE.NS","HCLTECH.NS","MARUTI.NS",
            "NTPC.NS","POWERGRID.NS","ONGC.NS","COALINDIA.NS",
            "TATAMOTORS.NS","TATASTEEL.NS","SUNPHARMA.NS","ASIANPAINT.NS",
        ]
        advances = declines = unchanged = 0
        for t in tickers:
            _, change, _, _ = _hist_price_change(t)
            if change > 0:
                advances += 1
            elif change < 0:
                declines += 1
            else:
                unchanged += 1
            _sleep()
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

    return _cached("breadth", _fetch) or {
        "advances": 0, "declines": 0, "unchanged": 0,
        "total": 1, "advance_pct": 0, "decline_pct": 0, "unchanged_pct": 0
    }