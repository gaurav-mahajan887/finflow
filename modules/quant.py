"""
modules/quant.py
─────────────────────────────────────────────────────────────
Quantitative Financial Analysis Engine for FinFlow.

Modules:
  1. Risk Metrics     — Sharpe, Beta, Volatility, Max Drawdown
  2. Portfolio Opt    — Markowitz MPT (min variance / max Sharpe)
  3. Signal Engine    — Rule-based BUY / HOLD / SELL signals
  4. Price Forecast   — Moving averages + optional ARIMA
  5. Correlation      — Pearson correlation matrix for a basket
  6. Data Export      — CSV / Excel builder (locked in UI)

All functions are self-contained and return plain dicts
or pandas DataFrames so Flask can serialize them easily.
─────────────────────────────────────────────────────────────
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# ── optional heavy imports (graceful fallback) ──────────────
try:
    from scipy.optimize import minimize
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    from statsmodels.tsa.arima.model import ARIMA
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False


BENCHMARK  = "^NSEI"          # NIFTY 50
RISK_FREE  = 0.065             # India 10-year Gsec ~6.5% annualised
TRADING_DAYS = 252


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _fetch_prices(ticker: str, period: str = "1y") -> pd.Series:
    """Return adjusted close price series. Raises on failure."""
    hist = yf.Ticker(ticker).history(period=period)
    if hist.empty:
        raise ValueError(f"No price data for {ticker}")
    return hist["Close"].dropna()


def _fetch_multi(tickers: list, period: str = "1y") -> pd.DataFrame:
    """Return DataFrame of adj close prices for multiple tickers."""
    frames = {}
    for t in tickers:
        try:
            frames[t] = _fetch_prices(t, period)
        except Exception:
            continue
    if not frames:
        raise ValueError("Could not fetch data for any ticker.")
    df = pd.DataFrame(frames)
    df.dropna(how="all", inplace=True)
    df.ffill(inplace=True)
    return df


def _safe(val, digits=4):
    try:
        v = float(val)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, digits)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
#  1. RISK METRICS
# ═══════════════════════════════════════════════════════════════

def get_risk_metrics(ticker: str, period: str = "1y") -> dict:
    """
    Returns:
      sharpe_ratio, beta, annualized_volatility,
      max_drawdown, annualized_return, var_95
    """
    try:
        prices    = _fetch_prices(ticker, period)
        bench_px  = _fetch_prices(BENCHMARK, period)

        returns   = prices.pct_change().dropna()
        bench_ret = bench_px.pct_change().dropna()

        # Align on common dates
        common = returns.index.intersection(bench_ret.index)
        ret    = returns.loc[common]
        bret   = bench_ret.loc[common]

        # ── Annualized Return ─────────────────────────────────
        ann_ret = ((1 + ret.mean()) ** TRADING_DAYS) - 1

        # ── Annualized Volatility ─────────────────────────────
        ann_vol = ret.std() * np.sqrt(TRADING_DAYS)

        # ── Sharpe Ratio ──────────────────────────────────────
        excess  = ann_ret - RISK_FREE
        sharpe  = excess / ann_vol if ann_vol != 0 else 0

        # ── Beta ──────────────────────────────────────────────
        cov     = np.cov(ret, bret)
        beta    = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 1.0

        # ── Max Drawdown ──────────────────────────────────────
        cumulative = (1 + ret).cumprod()
        rolling_max = cumulative.cummax()
        drawdown = (cumulative - rolling_max) / rolling_max
        max_dd   = drawdown.min()

        # ── Value at Risk (95%) ───────────────────────────────
        var_95 = np.percentile(ret, 5)

        # ── Sortino Ratio ─────────────────────────────────────
        downside = ret[ret < 0].std() * np.sqrt(TRADING_DAYS)
        sortino  = excess / downside if downside != 0 else 0

        # ── Drawdown series for chart ─────────────────────────
        dd_dates  = [str(d.date()) for d in drawdown.index[-60:]]
        dd_values = [_safe(v * 100) for v in drawdown.values[-60:]]

        # ── Price series for sparkline ────────────────────────
        price_dates  = [str(d.date()) for d in prices.index[-252:]]
        price_values = [_safe(v) for v in prices.values[-252:]]

        return {
            "ok":                  True,
            "ticker":              ticker,
            "period":              period,
            "annualized_return":   _safe(ann_ret * 100),
            "annualized_volatility": _safe(ann_vol * 100),
            "sharpe_ratio":        _safe(sharpe),
            "sortino_ratio":       _safe(sortino),
            "beta":                _safe(beta),
            "max_drawdown":        _safe(max_dd * 100),
            "var_95":              _safe(var_95 * 100),
            "current_price":       _safe(prices.iloc[-1]),
            "data_points":         len(ret),
            "dd_dates":            dd_dates,
            "dd_values":           dd_values,
            "price_dates":         price_dates,
            "price_values":        price_values,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  2. PORTFOLIO OPTIMIZATION (Markowitz MPT)
# ═══════════════════════════════════════════════════════════════

def optimize_portfolio(tickers: list, period: str = "1y") -> dict:
    """
    Markowitz Mean-Variance Optimization.
    Returns min-variance and max-Sharpe portfolios.
    """
    if not HAS_SCIPY:
        return {"ok": False, "error": "scipy not installed."}
    if len(tickers) < 2:
        return {"ok": False, "error": "Need at least 2 tickers."}
    if len(tickers) > 15:
        return {"ok": False, "error": "Max 15 tickers for optimization."}

    try:
        prices   = _fetch_multi(tickers, period)
        returns  = prices.pct_change().dropna()
        n        = len(returns.columns)
        tickers  = list(returns.columns)      # use only successfully fetched

        mean_ret = returns.mean() * TRADING_DAYS
        cov_mat  = returns.cov()  * TRADING_DAYS

        # ── Helper functions ──────────────────────────────────
        def port_perf(w):
            ret  = float(np.dot(w, mean_ret))
            vol  = float(np.sqrt(w @ cov_mat.values @ w))
            sharpe = (ret - RISK_FREE) / vol if vol > 0 else 0
            return ret, vol, sharpe

        def neg_sharpe(w):
            r, v, s = port_perf(w)
            return -s

        def port_vol(w):
            return port_perf(w)[1]

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds      = tuple((0.02, 0.6) for _ in range(n))
        w0          = np.array([1/n] * n)

        # ── Max Sharpe ────────────────────────────────────────
        res_sharpe = minimize(neg_sharpe, w0,
                              method="SLSQP",
                              bounds=bounds,
                              constraints=constraints,
                              options={"maxiter": 1000})

        # ── Min Variance ──────────────────────────────────────
        res_minvol = minimize(port_vol,   w0,
                              method="SLSQP",
                              bounds=bounds,
                              constraints=constraints,
                              options={"maxiter": 1000})

        def _weights_dict(w):
            return {t: round(float(wi) * 100, 2) for t, wi in zip(tickers, w)}

        sr, sv, ss   = port_perf(res_sharpe.x)
        mr, mv, ms   = port_perf(res_minvol.x)
        er, ev, es   = port_perf(w0)

        # ── Monte Carlo frontier (200 random portfolios) ──────
        mc_ret, mc_vol, mc_sharpe = [], [], []
        for _ in range(200):
            w = np.random.dirichlet(np.ones(n))
            r, v, s = port_perf(w)
            mc_ret.append(round(r * 100, 3))
            mc_vol.append(round(v * 100, 3))
            mc_sharpe.append(round(s, 3))

        # ── Individual stock stats ────────────────────────────
        stock_stats = []
        for t in tickers:
            r = float(mean_ret[t]) * 100
            v = float(returns[t].std() * np.sqrt(TRADING_DAYS)) * 100
            stock_stats.append({
                "ticker": t.replace(".NS",""),
                "return": round(r, 2),
                "vol":    round(v, 2),
                "sharpe": round((r/100 - RISK_FREE) / (v/100), 3) if v else 0,
            })

        return {
            "ok":      True,
            "tickers": [t.replace(".NS","") for t in tickers],
            "max_sharpe": {
                "weights":  _weights_dict(res_sharpe.x),
                "return":   round(sr * 100, 2),
                "vol":      round(sv * 100, 2),
                "sharpe":   round(ss, 3),
            },
            "min_vol": {
                "weights":  _weights_dict(res_minvol.x),
                "return":   round(mr * 100, 2),
                "vol":      round(mv * 100, 2),
                "sharpe":   round(ms, 3),
            },
            "equal_weight": {
                "weights":  _weights_dict(w0),
                "return":   round(er * 100, 2),
                "vol":      round(ev * 100, 2),
                "sharpe":   round(es, 3),
            },
            "frontier": {
                "returns":  mc_ret,
                "vols":     mc_vol,
                "sharpes":  mc_sharpe,
            },
            "stock_stats": stock_stats,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  3. BUY / SELL / HOLD SIGNAL ENGINE
# ═══════════════════════════════════════════════════════════════

def get_signals(tickers: list) -> dict:
    """
    Rule-based signal engine.
    For each ticker computes:
      momentum_1m, momentum_3m, volatility, sharpe, rsi,
      ma_cross (golden/death cross), volume_trend
    Then produces a composite score → BUY / HOLD / SELL tag.
    """
    results = []

    for ticker in tickers:
        try:
            prices  = _fetch_prices(ticker, "6mo")
            returns = prices.pct_change().dropna()

            # ── Momentum ──────────────────────────────────────
            mom_1m = float(prices.iloc[-1] / prices.iloc[-21] - 1) * 100  if len(prices) >= 21 else 0
            mom_3m = float(prices.iloc[-1] / prices.iloc[-63] - 1) * 100  if len(prices) >= 63 else 0

            # ── Volatility (30-day annualised) ────────────────
            vol_30 = float(returns.iloc[-30:].std() * np.sqrt(TRADING_DAYS)) * 100 if len(returns) >= 30 else 0

            # ── RSI (14-day) ──────────────────────────────────
            delta    = prices.diff().dropna()
            gain     = delta.clip(lower=0).rolling(14).mean()
            loss     = (-delta.clip(upper=0)).rolling(14).mean()
            rs       = gain / loss.replace(0, np.nan)
            rsi      = float(100 - 100 / (1 + rs.iloc[-1])) if not rs.empty else 50

            # ── Moving averages ───────────────────────────────
            ma20  = float(prices.rolling(20).mean().iloc[-1])
            ma50  = float(prices.rolling(50).mean().iloc[-1]) if len(prices) >= 50 else ma20
            ma200 = float(prices.rolling(200).mean().iloc[-1]) if len(prices) >= 200 else ma50
            curr  = float(prices.iloc[-1])

            golden_cross = ma20 > ma50   # short MA above long MA
            above_200    = curr > ma200

            # ── Sharpe (6mo) ──────────────────────────────────
            ann_ret = (1 + returns.mean()) ** TRADING_DAYS - 1
            ann_vol = returns.std() * np.sqrt(TRADING_DAYS)
            sharpe  = float((ann_ret - RISK_FREE) / ann_vol) if ann_vol != 0 else 0

            # ── Volume trend ──────────────────────────────────
            hist = yf.Ticker(ticker).history(period="6mo")
            vol_avg_10 = float(hist["Volume"].iloc[-10:].mean()) if not hist.empty else 0
            vol_avg_30 = float(hist["Volume"].iloc[-30:].mean()) if not hist.empty else 1
            vol_rising = vol_avg_10 > vol_avg_30

            # ── Composite scoring ─────────────────────────────
            score = 0

            # Momentum scoring
            if mom_1m > 5:   score += 2
            elif mom_1m > 0: score += 1
            elif mom_1m < -5: score -= 2
            else:             score -= 1

            if mom_3m > 10:  score += 2
            elif mom_3m > 0: score += 1
            else:             score -= 1

            # Sharpe scoring
            if sharpe > 1.5: score += 2
            elif sharpe > 0.5: score += 1
            elif sharpe < 0:   score -= 2

            # Volatility (lower = better for conservative signal)
            if vol_30 < 20:  score += 1
            elif vol_30 > 40: score -= 1

            # RSI scoring
            if rsi < 30:     score += 2   # oversold = potential buy
            elif rsi < 50:   score += 1
            elif rsi > 70:   score -= 2   # overbought
            elif rsi > 60:   score -= 1

            # MA signals
            if golden_cross: score += 2
            else:             score -= 1
            if above_200:    score += 1
            else:             score -= 1

            # Volume confirmation
            if vol_rising:   score += 1

            # ── Signal tag ────────────────────────────────────
            if score >= 5:
                signal = "BUY"
                color  = "green"
                reason = _signal_reason("BUY", mom_1m, sharpe, rsi, golden_cross)
            elif score <= 0:
                signal = "SELL"
                color  = "red"
                reason = _signal_reason("SELL", mom_1m, sharpe, rsi, golden_cross)
            else:
                signal = "HOLD"
                color  = "amber"
                reason = _signal_reason("HOLD", mom_1m, sharpe, rsi, golden_cross)

            results.append({
                "ticker":       ticker,
                "display":      ticker.replace(".NS", ""),
                "signal":       signal,
                "color":        color,
                "score":        score,
                "reason":       reason,
                "price":        round(curr, 2),
                "mom_1m":       round(mom_1m, 2),
                "mom_3m":       round(mom_3m, 2),
                "volatility":   round(vol_30, 2),
                "sharpe":       round(sharpe, 3),
                "rsi":          round(rsi, 1),
                "ma20":         round(ma20, 2),
                "ma50":         round(ma50, 2),
                "ma200":        round(ma200, 2),
                "golden_cross": golden_cross,
                "above_200ma":  above_200,
                "vol_rising":   vol_rising,
            })

        except Exception as e:
            results.append({
                "ticker":  ticker,
                "display": ticker.replace(".NS", ""),
                "signal":  "N/A",
                "color":   "muted",
                "error":   str(e),
            })

    return {"ok": True, "signals": results}


def _signal_reason(signal, mom_1m, sharpe, rsi, golden_cross):
    parts = []
    if signal == "BUY":
        if mom_1m > 0:     parts.append(f"positive 1M momentum (+{round(mom_1m,1)}%)")
        if sharpe > 0.5:   parts.append(f"strong risk-adjusted return (Sharpe {round(sharpe,2)})")
        if rsi < 50:       parts.append(f"RSI not overbought ({round(rsi,0)})")
        if golden_cross:   parts.append("golden cross (MA20 > MA50)")
    elif signal == "SELL":
        if mom_1m < 0:     parts.append(f"negative 1M momentum ({round(mom_1m,1)}%)")
        if sharpe < 0:     parts.append(f"negative risk-adjusted return (Sharpe {round(sharpe,2)})")
        if rsi > 65:       parts.append(f"RSI overbought ({round(rsi,0)})")
        if not golden_cross: parts.append("death cross (MA20 < MA50)")
    else:
        parts.append("mixed signals — neither clearly bullish nor bearish")
    return "; ".join(parts) if parts else "composite score in neutral range"


# ═══════════════════════════════════════════════════════════════
#  4. PRICE FORECASTING
# ═══════════════════════════════════════════════════════════════

def get_forecast(ticker: str, days: int = 30) -> dict:
    """
    Returns:
      - 7, 14, 30-day SMA forecasts
      - EMA forecast
      - ARIMA forecast (if statsmodels available)
      - Historical close + all series for charting
    """
    days = min(max(days, 7), 30)

    try:
        prices = _fetch_prices(ticker, "1y")
        if len(prices) < 60:
            return {"ok": False, "error": "Not enough historical data (need 60+ days)."}

        hist_dates  = [str(d.date()) for d in prices.index]
        hist_values = [_safe(v) for v in prices.values]
        last_price  = float(prices.iloc[-1])
        last_date   = prices.index[-1]

        # ── Generate future dates (skip weekends approx) ──────
        future_dates = []
        d = last_date
        added = 0
        while added < days:
            d = d + timedelta(days=1)
            if d.weekday() < 5:   # Mon-Fri
                future_dates.append(str(d.date()))
                added += 1

        # ── Moving Average Forecast ───────────────────────────
        sma20  = float(prices.rolling(20).mean().iloc[-1])
        sma50  = float(prices.rolling(50).mean().iloc[-1]) if len(prices) >= 50 else sma20
        ema20  = float(prices.ewm(span=20).mean().iloc[-1])

        # Drift = average daily return applied forward
        daily_drift = float(prices.pct_change().dropna().mean())

        sma_forecast = []
        ema_forecast = []
        for i in range(1, days + 1):
            # SMA forecast: walk towards SMA with drift
            target   = (sma20 + sma50) / 2
            sma_pred = last_price * (1 + daily_drift) ** i
            sma_pred = sma_pred * 0.6 + target * 0.4      # blend with MA
            ema_pred = ema20 * (1 + daily_drift * 0.5) ** i
            sma_forecast.append(_safe(sma_pred))
            ema_forecast.append(_safe(ema_pred))

        # ── ARIMA Forecast ────────────────────────────────────
        arima_forecast = None
        arima_error    = None
        if HAS_STATSMODELS:
            try:
                model   = ARIMA(prices.values, order=(2, 1, 2))
                fitted  = model.fit()
                arima_preds = fitted.forecast(steps=days)
                arima_forecast = [_safe(v) for v in arima_preds]
            except Exception as ae:
                arima_error = str(ae)

        # ── Confidence bands (±1 std of recent returns) ───────
        std_30 = float(prices.pct_change().dropna().iloc[-30:].std())
        upper  = [_safe(last_price * (1 + daily_drift) ** i + last_price * std_30 * np.sqrt(i))
                  for i in range(1, days + 1)]
        lower  = [_safe(last_price * (1 + daily_drift) ** i - last_price * std_30 * np.sqrt(i))
                  for i in range(1, days + 1)]

        # ── Summary targets ───────────────────────────────────
        sma7  = sma_forecast[6]  if len(sma_forecast)  >= 7  else None
        sma14 = sma_forecast[13] if len(sma_forecast)  >= 14 else None
        sma30 = sma_forecast[-1] if sma_forecast               else None

        return {
            "ok":            True,
            "ticker":        ticker,
            "days":          days,
            "last_price":    round(last_price, 2),
            "last_date":     str(last_date.date()),
            "hist_dates":    hist_dates[-120:],
            "hist_values":   hist_values[-120:],
            "future_dates":  future_dates,
            "sma_forecast":  sma_forecast,
            "ema_forecast":  ema_forecast,
            "arima_forecast": arima_forecast,
            "arima_error":   arima_error,
            "upper_band":    upper,
            "lower_band":    lower,
            "targets": {
                "7d_sma":   sma7,
                "14d_sma":  sma14,
                "30d_sma":  sma30,
                "7d_arima":  arima_forecast[6]  if arima_forecast and len(arima_forecast) >= 7  else None,
                "30d_arima": arima_forecast[-1] if arima_forecast else None,
            },
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "ema20": round(ema20, 2),
            "daily_drift_pct": round(daily_drift * 100, 4),
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  5. CORRELATION MATRIX
# ═══════════════════════════════════════════════════════════════

def get_correlation(tickers: list, period: str = "1y") -> dict:
    """Returns Pearson correlation matrix as a dict-of-dicts for JSON."""
    if len(tickers) < 2:
        return {"ok": False, "error": "Need at least 2 tickers."}
    if len(tickers) > 12:
        tickers = tickers[:12]

    try:
        prices   = _fetch_multi(tickers, period)
        returns  = prices.pct_change().dropna()
        corr_df  = returns.corr().round(3)

        labels = [t.replace(".NS","") for t in corr_df.columns.tolist()]
        matrix = []
        for i, row_t in enumerate(corr_df.index):
            row = []
            for j, col_t in enumerate(corr_df.columns):
                row.append(_safe(corr_df.loc[row_t, col_t]))
            matrix.append(row)

        return {
            "ok":     True,
            "labels": labels,
            "matrix": matrix,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  6. DATA EXPORT  (CSV builder — locked in UI, backend ready)
# ═══════════════════════════════════════════════════════════════

def build_export_csv(ticker: str) -> str:
    """
    Returns a CSV string containing risk metrics + signal + forecast targets.
    Called from the (premium-locked) /api/export/<ticker> route.
    """
    try:
        risk     = get_risk_metrics(ticker)
        signals  = get_signals([ticker])
        forecast = get_forecast(ticker, days=30)

        sig = signals["signals"][0] if signals["ok"] and signals["signals"] else {}

        rows = [
            ["Metric", "Value"],
            ["Ticker",                  ticker],
            ["Current Price",           risk.get("current_price")],
            ["Annualized Return %",     risk.get("annualized_return")],
            ["Annualized Volatility %", risk.get("annualized_volatility")],
            ["Sharpe Ratio",            risk.get("sharpe_ratio")],
            ["Sortino Ratio",           risk.get("sortino_ratio")],
            ["Beta vs NIFTY50",         risk.get("beta")],
            ["Max Drawdown %",          risk.get("max_drawdown")],
            ["VaR 95%",                 risk.get("var_95")],
            ["Signal",                  sig.get("signal")],
            ["Signal Score",            sig.get("score")],
            ["RSI",                     sig.get("rsi")],
            ["Momentum 1M %",           sig.get("mom_1m")],
            ["Momentum 3M %",           sig.get("mom_3m")],
            ["7D Forecast (SMA)",       forecast.get("targets", {}).get("7d_sma")],
            ["30D Forecast (SMA)",      forecast.get("targets", {}).get("30d_sma")],
            ["7D Forecast (ARIMA)",     forecast.get("targets", {}).get("7d_arima")],
            ["30D Forecast (ARIMA)",    forecast.get("targets", {}).get("30d_arima")],
            ["Generated",               datetime.now().strftime("%Y-%m-%d %H:%M")],
        ]

        lines = [",".join(str(cell) if cell is not None else "" for cell in row)
                 for row in rows]
        return "\n".join(lines)

    except Exception as e:
        return f"Error,{str(e)}"
