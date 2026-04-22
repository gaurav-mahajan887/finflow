"""
modules/ai_insights.py
─────────────────────────────────────────────────────────────
Rule-based AI Insight Generator for FinFlow.

Produces human-readable, analyst-style commentary from
quantitative metrics. No LLM API key required — all logic
is deterministic and runs offline.

Each insight function returns a structured dict with:
  - summary      : one-sentence headline
  - sections     : list of {title, body, icon, sentiment}
  - verdict      : POSITIVE / NEUTRAL / NEGATIVE / CAUTION
  - verdict_text : one-line plain-English conclusion
─────────────────────────────────────────────────────────────
"""

from datetime import datetime


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def _sent(val, good, ok, flip=False):
    """Return sentiment string based on thresholds."""
    if val is None or val == "N/A":
        return "neutral"
    try:
        v = float(val)
    except Exception:
        return "neutral"
    if flip:  # lower is better (volatility, drawdown, debt)
        if v <= good: return "positive"
        if v <= ok:   return "neutral"
        return "negative"
    else:     # higher is better
        if v >= good: return "positive"
        if v >= ok:   return "neutral"
        return "negative"


def _icon(sentiment):
    return {"positive": "✅", "neutral": "🟡", "negative": "🔴"}.get(sentiment, "⚪")


def _pct(val):
    if val is None: return "N/A"
    return f"{val:+.2f}%"


def _round(val, d=2):
    if val is None: return "N/A"
    try: return round(float(val), d)
    except: return "N/A"


# ─────────────────────────────────────────
#  RISK INSIGHTS
# ─────────────────────────────────────────

def insights_from_risk(risk: dict, ticker: str) -> dict:
    """Generate full analyst commentary from risk metrics."""

    if not risk.get("ok"):
        return {"ok": False, "error": risk.get("error", "No data")}

    sharpe  = risk.get("sharpe_ratio")
    beta    = risk.get("beta")
    vol     = risk.get("annualized_volatility")
    drawdown = risk.get("max_drawdown")
    ret     = risk.get("annualized_return")
    var95   = risk.get("var_95")
    sortino = risk.get("sortino_ratio")

    sections = []

    # ── Return ────────────────────────────────────────────────
    r_sent = _sent(ret, 15, 8)
    sections.append({
        "title": "Annualized Return",
        "icon":  _icon(r_sent),
        "sentiment": r_sent,
        "body": (
            f"The stock has delivered an annualized return of {_pct(ret)}. "
            + (f"This outperforms a typical fixed-income benchmark, suggesting "
               f"the stock has rewarded investors adequately over the period."
               if ret and float(ret) > 10 else
               f"This is below what most equity investors target (12–15%), "
               f"indicating subdued price appreciation over the analysis period."
               if ret and float(ret) < 8 else
               f"Returns are in the moderate range, in line with market expectations.")
        )
    })

    # ── Sharpe ───────────────────────────────────────────────
    s_sent = _sent(sharpe, 1.5, 0.5)
    if sharpe is not None:
        if float(sharpe) >= 1.5:
            sharpe_body = (f"Excellent risk-adjusted performance with a Sharpe ratio of {_round(sharpe)}. "
                           f"The stock has generated strong returns relative to the risk taken — "
                           f"a ratio above 1.5 is generally considered very attractive.")
        elif float(sharpe) >= 0.5:
            sharpe_body = (f"Moderate risk-adjusted return (Sharpe: {_round(sharpe)}). "
                           f"The stock is compensating investors for risk, though not exceptionally. "
                           f"A Sharpe above 1.0 would be considered strong.")
        else:
            sharpe_body = (f"Poor risk-adjusted return (Sharpe: {_round(sharpe)}). "
                           f"The returns do not adequately compensate for the risk taken. "
                           f"Consider whether the risk exposure is justified.")
        sections.append({
            "title": "Risk-Adjusted Return (Sharpe)",
            "icon":  _icon(s_sent), "sentiment": s_sent, "body": sharpe_body
        })

    # ── Volatility ───────────────────────────────────────────
    v_sent = _sent(vol, 20, 35, flip=True)
    if vol is not None:
        fv = float(vol)
        if fv < 20:
            vol_body = (f"Annualized volatility of {_round(vol)}% is low, indicating a relatively stable stock. "
                        f"Suitable for conservative investors seeking steady appreciation.")
        elif fv < 35:
            vol_body = (f"Moderate volatility at {_round(vol)}% annualized. "
                        f"Typical for mid-to-large cap Indian equities. "
                        f"Investors should expect price swings of ~{_round(fv/16, 1)}% per week.")
        else:
            vol_body = (f"High volatility at {_round(vol)}% annualized. "
                        f"The stock carries significant price risk. "
                        f"Only suitable for investors with a high risk tolerance and a long time horizon.")
        sections.append({
            "title": "Price Volatility",
            "icon":  _icon(v_sent), "sentiment": v_sent, "body": vol_body
        })

    # ── Beta ─────────────────────────────────────────────────
    if beta is not None:
        fb = float(beta)
        if fb < 0.7:
            beta_body = (f"Beta of {_round(beta)} indicates a defensive stock. "
                         f"It moves significantly less than NIFTY 50, making it a good portfolio stabilizer.")
            b_sent = "positive"
        elif fb <= 1.2:
            beta_body = (f"Beta of {_round(beta)} is near-market. "
                         f"The stock broadly tracks NIFTY 50 movements — "
                         f"a 1% market move implies roughly a {_round(beta)}% move in this stock.")
            b_sent = "neutral"
        elif fb <= 1.8:
            beta_body = (f"Beta of {_round(beta)} indicates an aggressive stock. "
                         f"It amplifies market moves — useful in bull markets but painful in corrections.")
            b_sent = "neutral"
        else:
            beta_body = (f"Very high beta of {_round(beta)}. "
                         f"This stock is highly sensitive to market movements and carries elevated systematic risk.")
            b_sent = "negative"
        sections.append({
            "title": "Market Sensitivity (Beta)",
            "icon":  _icon(b_sent), "sentiment": b_sent, "body": beta_body
        })

    # ── Max Drawdown ──────────────────────────────────────────
    dd_sent = _sent(drawdown, -15, -30, flip=False)  # drawdown is negative; less negative = better
    if drawdown is not None:
        fd = float(drawdown)
        if fd > -15:
            dd_body = (f"Maximum drawdown of {_round(fd)}% is contained. "
                       f"The stock has shown resilience, with recoveries from declines being relatively quick.")
        elif fd > -30:
            dd_body = (f"Maximum drawdown of {_round(fd)}% is moderate. "
                       f"At its worst, the stock fell {abs(_round(fd))}% from a peak — "
                       f"significant but within typical equity market ranges.")
        else:
            dd_body = (f"Severe maximum drawdown of {_round(fd)}%. "
                       f"The stock has experienced steep declines from peak prices. "
                       f"This level of drawdown can be emotionally and financially challenging for investors.")
        sections.append({
            "title": "Worst-Case Decline (Max Drawdown)",
            "icon":  "✅" if fd > -15 else ("🟡" if fd > -30 else "🔴"),
            "sentiment": "positive" if fd > -15 else ("neutral" if fd > -30 else "negative"),
            "body": dd_body
        })

    # ── VaR ───────────────────────────────────────────────────
    if var95 is not None:
        sections.append({
            "title": "Value at Risk (95% confidence)",
            "icon":  "📊",
            "sentiment": "neutral",
            "body": (f"On any given day, there is a 5% chance the stock loses more than "
                     f"{abs(_round(float(var95), 2))}% of its value. "
                     f"This is your daily worst-case estimate at 95% confidence — "
                     f"a standard risk management metric used by institutional investors.")
        })

    # ── Overall Verdict ───────────────────────────────────────
    positives = sum(1 for s in sections if s.get("sentiment") == "positive")
    negatives = sum(1 for s in sections if s.get("sentiment") == "negative")

    if positives >= 3 and negatives <= 1:
        verdict = "POSITIVE"
        verdict_text = (f"{ticker.replace('.NS','')} shows strong fundamentals on a risk-adjusted basis. "
                        f"The metrics suggest a well-performing stock relative to the risk it carries.")
    elif negatives >= 3:
        verdict = "NEGATIVE"
        verdict_text = (f"{ticker.replace('.NS','')} shows concerning risk metrics. "
                        f"The stock may not be adequately compensating investors for the risk taken.")
    elif negatives >= 2:
        verdict = "CAUTION"
        verdict_text = (f"{ticker.replace('.NS','')} shows mixed signals — "
                        f"some strengths but notable risk concerns worth monitoring closely.")
    else:
        verdict = "NEUTRAL"
        verdict_text = (f"{ticker.replace('.NS','')} shows balanced risk-return characteristics. "
                        f"Neither strongly attractive nor concerning at current levels.")

    summary = (
        f"{ticker.replace('.NS','')} has delivered {_pct(ret)} annualized with a Sharpe of "
        f"{_round(sharpe)}, beta of {_round(beta)} vs NIFTY 50, "
        f"and a max drawdown of {_round(drawdown)}%."
    )

    return {
        "ok":          True,
        "ticker":      ticker,
        "generated":   datetime.now().strftime("%d %b %Y, %H:%M"),
        "summary":     summary,
        "sections":    sections,
        "verdict":     verdict,
        "verdict_text": verdict_text,
        "positives":   positives,
        "negatives":   negatives,
    }


# ─────────────────────────────────────────
#  SIGNAL INSIGHTS
# ─────────────────────────────────────────

def insights_from_signal(signal_row: dict) -> dict:
    """Generate commentary from a single signal dict."""
    if not signal_row or signal_row.get("signal") == "N/A":
        return {"ok": False, "error": "No signal data"}

    sig   = signal_row.get("signal")
    mom1m = signal_row.get("mom_1m", 0)
    mom3m = signal_row.get("mom_3m", 0)
    rsi   = signal_row.get("rsi", 50)
    sharpe= signal_row.get("sharpe", 0)
    vol   = signal_row.get("volatility", 25)
    gc    = signal_row.get("golden_cross", False)
    a200  = signal_row.get("above_200ma", False)

    lines = []

    # Momentum
    if mom1m > 5:
        lines.append(f"Strong positive momentum over the last month (+{round(mom1m,1)}%), "
                     f"suggesting active buying interest.")
    elif mom1m < -5:
        lines.append(f"Negative 1-month momentum ({round(mom1m,1)}%) indicates recent selling pressure.")
    else:
        lines.append(f"Flat near-term momentum ({round(mom1m,1)}% over 1 month) — price is consolidating.")

    if mom3m > 15:
        lines.append(f"Excellent 3-month trend (+{round(mom3m,1)}%) confirms sustained buying interest.")
    elif mom3m < -10:
        lines.append(f"The 3-month trend is negative ({round(mom3m,1)}%), indicating a broader downtrend.")

    # RSI
    if rsi < 30:
        lines.append(f"RSI of {round(rsi,0)} signals oversold conditions — a potential reversal or bounce opportunity.")
    elif rsi > 70:
        lines.append(f"RSI of {round(rsi,0)} is in overbought territory — caution on new entries at current prices.")
    else:
        lines.append(f"RSI of {round(rsi,0)} is in a neutral zone, providing no directional bias.")

    # MA cross
    if gc:
        lines.append("Golden cross detected (20-day MA above 50-day MA) — a classic bullish technical setup.")
    else:
        lines.append("Death cross in effect (20-day MA below 50-day MA) — bearish technical structure.")

    if a200:
        lines.append("Price is trading above its 200-day moving average — long-term trend is intact.")
    else:
        lines.append("Price is below the 200-day moving average — the long-term trend is under pressure.")

    # Sharpe
    if sharpe > 1:
        lines.append(f"Strong risk-adjusted returns (Sharpe: {round(sharpe,2)}) over the analysis window.")
    elif sharpe < 0:
        lines.append(f"Negative Sharpe ({round(sharpe,2)}) suggests the stock is destroying risk-adjusted value.")

    conclusion = {
        "BUY":  (f"The composite signal is BUY (score: {signal_row.get('score')}). "
                 f"Multiple indicators align bullishly — momentum, technicals and risk metrics support a positive outlook."),
        "SELL": (f"The composite signal is SELL (score: {signal_row.get('score')}). "
                 f"Deteriorating momentum, weak technicals and poor risk-adjusted returns suggest caution."),
        "HOLD": (f"The composite signal is HOLD (score: {signal_row.get('score')}). "
                 f"Mixed signals — existing holders may stay the course but new entries are not clearly warranted."),
    }.get(sig, "Insufficient data for a conclusion.")

    return {
        "ok":         True,
        "signal":     sig,
        "ticker":     signal_row.get("ticker"),
        "paragraphs": lines,
        "conclusion": conclusion,
    }


# ─────────────────────────────────────────
#  FORECAST INSIGHTS
# ─────────────────────────────────────────

def insights_from_forecast(forecast: dict) -> dict:
    """Generate commentary from forecast data."""
    if not forecast.get("ok"):
        return {"ok": False, "error": forecast.get("error")}

    last    = forecast["last_price"]
    t7_sma  = forecast["targets"].get("7d_sma")
    t30_sma = forecast["targets"].get("30d_sma")
    t7_ar   = forecast["targets"].get("7d_arima")
    t30_ar  = forecast["targets"].get("30d_arima")
    drift   = forecast.get("daily_drift_pct", 0)

    lines = []
    lines.append(
        f"Based on historical price behaviour and moving-average models, "
        f"the stock is currently priced at ₹{last}."
    )

    if t7_sma:
        chg = round((float(t7_sma) - last) / last * 100, 2)
        lines.append(
            f"The 7-day SMA-based forecast projects a price of ₹{round(float(t7_sma),2)} "
            f"({'▲ +' if chg>0 else '▼ '}{abs(chg)}% from current)."
        )

    if t30_sma:
        chg = round((float(t30_sma) - last) / last * 100, 2)
        lines.append(
            f"The 30-day price target (SMA model) is ₹{round(float(t30_sma),2)} "
            f"({'▲ +' if chg>0 else '▼ '}{abs(chg)}%)."
        )

    if t7_ar:
        lines.append(
            f"The ARIMA model, which captures autocorrelation in price series, "
            f"projects ₹{round(float(t7_ar),2)} in 7 days."
        )

    if drift and float(drift) != 0:
        lines.append(
            f"The stock's average daily drift is {round(float(drift),4)}% — "
            f"{'positive, suggesting a mild upward bias' if float(drift) > 0 else 'negative, suggesting a mild downward bias'} "
            f"in recent price action."
        )

    lines.append(
        "⚠️ Forecasts are statistical projections based on historical data and should not be "
        "used as standalone investment decisions. Markets are influenced by many factors that models cannot predict."
    )

    return {"ok": True, "paragraphs": lines}
