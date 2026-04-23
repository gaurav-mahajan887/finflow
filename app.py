import time
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
from flask import (Flask, render_template, request,
                   jsonify, session, redirect, url_for, flash)

from modules.quant import (
    get_risk_metrics, optimize_portfolio,
    get_signals, get_forecast, get_correlation, build_export_csv,
)
from modules.ai_insights import (
    insights_from_risk, insights_from_signal, insights_from_forecast,
)

from modules.market import (
    get_trending_stocks, get_gainers_losers, get_stock_data,
    get_most_active, get_52w_breakouts, get_watchlist_data,
    get_indices_data, get_ticker_bar_stocks, get_todays_stocks,
    get_sector_data, get_market_breadth, get_stock_financials,
)
from modules.financials import (
    get_full_financials, run_dcf,
    generate_research_report, compare_stocks,
)
from modules.auth import init_db, signup_user, login_user, get_user

app = Flask(__name__)
app.secret_key = "finflow_secret_key_change_in_prod"

# Init DB on startup
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"[auth] DB init warning: {e}")


# ═══════════════════════════════════════════
#  CACHE  (5-min TTL)
# ═══════════════════════════════════════════
_stock_cache: dict = {}
_CACHE_TTL = 300


def cached_stock_data(ticker: str, period: str = "1mo"):
    key = f"{ticker}:{period}"
    now = time.time()
    entry = _stock_cache.get(key)
    if entry and (now - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    data = get_stock_data(ticker, period)
    if data:
        _stock_cache[key] = {"data": data, "ts": now}
    return data


def fetch_parallel(tickers: list, period: str = "1mo") -> list:
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda t: cached_stock_data(t, period), tickers))
    return [r for r in results if r is not None]


# ═══════════════════════════════════════════
#  HOME
# ═══════════════════════════════════════════
@app.route('/')
def home():
    return render_template('home.html')


# ═══════════════════════════════════════════
#  AUTH — CHECK
# ═══════════════════════════════════════════
@app.route('/check-auth')
def check_auth():
    return jsonify({
        "logged_in": "user" in session,
        "username":  session.get("user", None),
    })


# ═══════════════════════════════════════════
#  AUTH — SIGNUP
# ═══════════════════════════════════════════
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user' in session:
        return redirect(url_for('home'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        result = signup_user(username, email, password)
        if result['ok']:
            session['user'] = username
            flash('Account created! Welcome to FinFlow.', 'success')
            return redirect(url_for('home'))
        else:
            error = result['error']

    return render_template('auth.html', mode='signup', error=error)


# ═══════════════════════════════════════════
#  AUTH — LOGIN
# ═══════════════════════════════════════════
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('home'))

    error = None
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password   = request.form.get('password', '')

        result = login_user(identifier, password)
        if result['ok']:
            session['user'] = result['username']
            flash(f"Welcome back, {result['username']}!", 'success')
            return redirect(request.args.get('next') or url_for('home'))
        else:
            error = result['error']

    return render_template('auth.html', mode='login', error=error)


# ═══════════════════════════════════════════
#  AUTH — LOGOUT
# ═══════════════════════════════════════════
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))


# ═══════════════════════════════════════════
#  MARKET DASHBOARD
# ═══════════════════════════════════════════
@app.route('/market')
def market():
    trending        = get_trending_stocks()
    gainers, losers = get_gainers_losers()
    active          = get_most_active()
    highs, lows     = get_52w_breakouts()
    indices         = get_indices_data()
    todays_stocks   = get_todays_stocks()
    sectors         = get_sector_data()
    breadth         = get_market_breadth()
    return render_template('market.html',
        trending=trending, gainers=gainers, losers=losers,
        active=active, highs=highs, lows=lows,
        indices=indices, todays_stocks=todays_stocks,
        sectors=sectors, breadth=breadth, overview=[])


# ═══════════════════════════════════════════
#  STOCK DETAIL
# ═══════════════════════════════════════════
@app.route('/stock/<ticker>')
def stock_detail(ticker):
    period     = request.args.get('period', '1y')
    data       = cached_stock_data(ticker, period)
    if not data:
        return "Stock not found", 404
    financials = get_stock_financials(ticker)

    # Rich financial tables (pulled fresh for detail page)
    fin_tables = _get_financial_tables(ticker)

    return render_template('stock_detail.html',
        data=data, ticker=ticker, period=period,
        financials=financials, fin_tables=fin_tables)


def _get_financial_tables(ticker: str) -> dict:
    """Return structured annual data for rendering in tables."""
    try:
        stock = yf.Ticker(ticker)
        fin   = stock.financials
        bs    = stock.balance_sheet
        cf    = stock.cashflow

        def to_cr(val):
            try: return round(float(val) / 1e7, 2)
            except: return None

        def extract(df, rows):
            if df is None or df.empty:
                return {"years": [], "rows": []}
            years = [str(c.year) if hasattr(c, 'year') else str(c)[:4]
                     for c in df.columns[:4]]
            result = []
            for label, keys in rows:
                for k in keys:
                    if k in df.index:
                        vals = [to_cr(df.loc[k].iloc[i])
                                for i in range(min(4, len(df.columns)))]
                        result.append({"label": label, "values": vals})
                        break
            return {"years": years, "rows": result}

        income = extract(fin, [
            ("Revenue",         ["Total Revenue"]),
            ("Gross Profit",    ["Gross Profit"]),
            ("EBITDA",          ["EBITDA", "Normalized EBITDA"]),
            ("Operating Income",["Operating Income", "Ebit"]),
            ("Net Income",      ["Net Income"]),
            ("EPS",             ["Basic EPS", "Diluted EPS"]),
        ])

        balance = extract(bs, [
            ("Total Assets",        ["Total Assets"]),
            ("Current Assets",      ["Total Current Assets", "Current Assets"]),
            ("Total Liabilities",   ["Total Liab", "Total Liabilities Net Minority Interest"]),
            ("Current Liabilities", ["Total Current Liabilities", "Current Liabilities"]),
            ("Total Debt",          ["Total Debt", "Long Term Debt"]),
            ("Shareholders Equity", ["Total Stockholder Equity", "Stockholders Equity", "Total Equity"]),
            ("Cash & Equivalents",  ["Cash And Cash Equivalents", "Cash"]),
        ])

        cashflow = extract(cf, [
            ("Operating CF",   ["Total Cash From Operating Activities", "Operating Cash Flow"]),
            ("CapEx",          ["Capital Expenditures"]),
            ("Investing CF",   ["Total Cashflows From Investing Activities"]),
            ("Financing CF",   ["Total Cash From Financing Activities"]),
        ])

        # Compute Free Cash Flow
        if cashflow["rows"]:
            op_row    = next((r for r in cashflow["rows"] if r["label"] == "Operating CF"), None)
            capex_row = next((r for r in cashflow["rows"] if r["label"] == "CapEx"), None)
            if op_row and capex_row:
                fcf_vals = []
                for o, c in zip(op_row["values"], capex_row["values"]):
                    if o is not None and c is not None:
                        fcf_vals.append(round(o - abs(c), 2))
                    else:
                        fcf_vals.append(None)
                cashflow["rows"].append({"label": "Free Cash Flow", "values": fcf_vals})

        return {"income": income, "balance": balance, "cashflow": cashflow}

    except Exception as e:
        print(f"[fin_tables] {e}")
        return {"income": {"years": [], "rows": []},
                "balance": {"years": [], "rows": []},
                "cashflow": {"years": [], "rows": []}}


# ═══════════════════════════════════════════
#  WATCHLIST / PORTFOLIO
# ═══════════════════════════════════════════
@app.route('/watchlist')
def watchlist():
    return render_template('watchlist.html')


@app.route('/watchlist-data/<ticker>')
def watchlist_data(ticker):
    data = get_watchlist_data([ticker])
    return jsonify(data[0] if data else {})


@app.route('/stock-data/<ticker>')
def stock_data_api(ticker):
    period = request.args.get('period', '1y')
    data   = cached_stock_data(ticker, period)
    return jsonify(data or {})


@app.route('/save-watchlist', methods=['POST'])
def save_watchlist():
    session['watchlist'] = request.json.get("watchlist", [])
    return jsonify({"status": "saved"})


@app.route('/get-watchlist')
def get_watchlist():
    return jsonify(session.get("watchlist", []))


# ═══════════════════════════════════════════
#  AUTOCOMPLETE
# ═══════════════════════════════════════════
@app.route("/autocomplete")
def autocomplete():
    query = request.args.get("q", "").upper()
    tickers = [
        "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS",
        "ICICIBANK.NS","SBIN.NS","WIPRO.NS","AXISBANK.NS",
        "LT.NS","BAJFINANCE.NS","HCLTECH.NS","MARUTI.NS",
        "NTPC.NS","ONGC.NS","COALINDIA.NS","TATAMOTORS.NS",
        "TATASTEEL.NS","SUNPHARMA.NS","ASIANPAINT.NS","POWERGRID.NS",
    ]
    results = []
    for t in tickers:
        if query in t:
            try:
                d = cached_stock_data(t, "1mo")
                if d:
                    results.append({"ticker": t, "name": d["name"], "price": d["price"]})
            except Exception:
                continue
    return jsonify(results[:6])


# ═══════════════════════════════════════════
#  MARKET JSON APIs
# ═══════════════════════════════════════════
@app.route('/api/indices')
def api_indices():
    return jsonify(get_indices_data())

@app.route('/api/ticker-bar')
def api_ticker_bar():
    return jsonify(get_ticker_bar_stocks())

@app.route('/api/sectors')
def api_sectors():
    return jsonify(get_sector_data())

@app.route('/api/breadth')
def api_breadth():
    return jsonify(get_market_breadth())

@app.route('/api/todays-stocks')
def api_todays_stocks():
    return jsonify(get_todays_stocks())

@app.route('/api/financials/<ticker>')
def api_financials(ticker):
    return jsonify(get_stock_financials(ticker))

@app.route('/api/financial-preview/<ticker>')
def api_financial_preview(ticker):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        return jsonify({
            "ok": True, "name": info.get("longName", ticker),
            "ticker": ticker, "sector": info.get("sector", "N/A"),
            "price": round(float(price), 2),
            "pe":    round(float(info.get("trailingPE")     or 0), 2),
            "pb":    round(float(info.get("priceToBook")    or 0), 2),
            "roe":   round(float(info.get("returnOnEquity") or 0) * 100, 2),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/scores/<ticker>')
def api_scores(ticker):
    data = get_full_financials(ticker)
    if not data["ok"]:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "scores": data["scores"],
                    "flags": data["flags"], "insights": data["insights"]})


# ═══════════════════════════════════════════
#  NEWS
# ═══════════════════════════════════════════
def get_market_news(limit=12):
    """
    Fetch recent news headlines using yfinance.
    Falls back to curated mock data if unavailable.
    """
    try:
        # Pull news from a basket of major tickers
        tickers = ["RELIANCE.NS", "TCS.NS", "^NSEI"]
        all_news = []
        seen = set()
        for t in tickers:
            try:
                stock = yf.Ticker(t)
                news  = stock.news or []
                for item in news[:6]:
                    title = item.get("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        all_news.append({
                            "title":     title,
                            "source":    item.get("publisher", "Market News"),
                            "url":       item.get("link", "#"),
                            "time":      item.get("providerPublishTime", 0),
                            "thumbnail": (item.get("thumbnail") or {})
                                          .get("resolutions", [{}])[0]
                                          .get("url", ""),
                        })
            except Exception:
                continue

        # Sort by time descending
        all_news.sort(key=lambda x: x["time"], reverse=True)
        return all_news[:limit]

    except Exception:
        # Fallback mock news
        return [
            {"title": "NIFTY 50 touches fresh highs amid strong FII inflows",
             "source": "Economic Times", "url": "https://economictimes.indiatimes.com",
             "time": 0, "thumbnail": ""},
            {"title": "RBI holds repo rate; markets rally on policy continuity",
             "source": "Mint", "url": "https://livemint.com", "time": 0, "thumbnail": ""},
            {"title": "Reliance Industries Q3 results beat analyst estimates",
             "source": "Business Standard", "url": "https://business-standard.com",
             "time": 0, "thumbnail": ""},
        ]


@app.route('/news')
def news():
    articles = get_market_news(limit=12)
    return render_template('news.html', articles=articles)


@app.route('/api/news')
def api_news():
    limit = int(request.args.get('limit', 6))
    return jsonify(get_market_news(limit=limit))


# ═══════════════════════════════════════════
#  FINANCIAL TOOLS HOME
# ═══════════════════════════════════════════
@app.route('/financials')
def financials_home():
    return render_template('financials_home.html')

@app.route('/tools')
def tools():
    return render_template('tools.html')


# ═══════════════════════════════════════════
#  DCF  (FIXED: auto-fetch FCF from ticker)
# ═══════════════════════════════════════════
@app.route('/input', methods=['GET', 'POST'])
def input_page():
    fin_data   = None
    dcf_result = None
    ticker     = ""
    error      = None
    # Preserve slider values across POST
    growth   = float(request.form.get('growth', 10))
    disc     = float(request.form.get('discount', 12))
    tg       = float(request.form.get('terminal_growth', 4))

    if request.method == 'POST':
        ticker = request.form.get('ticker', '').strip().upper()
        fcf_manual = request.form.get('fcf', '').strip()

        try:
            if ticker:
                # ALWAYS fetch financials when ticker is given
                fin_data = get_full_financials(ticker)
                if fin_data["ok"] and fin_data["cashflow"]["fcf_0"]:
                    # Auto-use fetched FCF (convert from Cr back to raw)
                    fcf = fin_data["cashflow"]["fcf_0"] * 1e7
                elif fcf_manual:
                    fcf = float(fcf_manual)
                else:
                    error = (f"Could not auto-fetch FCF for {ticker}. "
                             "Please enter Free Cash Flow manually.")
                    fcf = None
            elif fcf_manual:
                fcf = float(fcf_manual)
            else:
                error = "Enter a ticker symbol OR a Free Cash Flow value."
                fcf = None

            if fcf and not error:
                dcf_result = run_dcf(fcf, growth, disc, tg)
                if dcf_result["ok"] and fin_data and fin_data["ok"]:
                    mkt = fin_data["company"]["price"]
                    if mkt:
                        dcf_result["market_price"] = mkt
                        upside = round((dcf_result["intrinsic"] - mkt) / mkt * 100, 1)
                        dcf_result["upside"]  = upside
                        dcf_result["verdict"] = (
                            "Undervalued" if upside > 15 else
                            "Overvalued"  if upside < -15 else
                            "Fairly Valued"
                        )
                # Store assumptions for display
                dcf_result["assumptions"] = {
                    "fcf":    round(fcf / 1e7, 2),
                    "growth": growth,
                    "discount": disc,
                    "terminal_growth": tg,
                }

        except Exception as e:
            error = str(e)

    return render_template('input.html',
        fin_data=fin_data, dcf_result=dcf_result,
        ticker=ticker, error=error,
        growth=growth, disc=disc, tg=tg)


# ═══════════════════════════════════════════
#  BALANCE SHEET
# ═══════════════════════════════════════════
@app.route('/balance-sheet', methods=['GET', 'POST'])
def balance_sheet():
    fin_data = None; result = None; ticker = ""; error = None
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').strip()
        try:
            if ticker:
                fin_data = get_full_financials(ticker)
                if fin_data["ok"]:
                    b = fin_data["balance"]
                    ca = b["ca_0"] or 0; ta = b["ta_0"] or 0
                    nca = round(ta - ca, 2); cl = b["cl_0"] or 0
                    tl = b["tl_0"] or 0; ncl = round(tl - cl, 2); eq = b["eq_0"] or 0
                else:
                    error = fin_data.get("error")
            else:
                ca  = float(request.form.get('current_assets', 0))
                nca = float(request.form.get('non_current_assets', 0))
                cl  = float(request.form.get('current_liabilities', 0))
                ncl = float(request.form.get('non_current_liabilities', 0))
                eq  = float(request.form.get('equity', 0))
                ta  = ca + nca; tl = cl + ncl
            if not error:
                result = {
                    "ca": ca, "nca": nca, "cl": cl, "ncl": ncl,
                    "equity": eq, "total_assets": ta, "total_liab": tl,
                    "current_ratio": round(ca/cl,2) if cl else None,
                    "de_ratio":      round(tl/eq,2) if eq else None,
                    "equity_ratio":  round(eq/ta,2) if ta else None,
                    "balanced":      abs(ta-(tl+eq)) < 1,
                }
                r = result
                r["liquidity_tag"] = ("Strong" if (r["current_ratio"] or 0)>=2 else
                    "Adequate" if (r["current_ratio"] or 0)>=1.2 else "Weak")
                r["leverage_tag"]  = ("Low" if (r["de_ratio"] or 0)<0.5 else
                    "Moderate" if (r["de_ratio"] or 0)<1.5 else "High")
        except Exception as e:
            error = str(e)
    return render_template('balance_sheet.html',
        fin_data=fin_data, result=result, ticker=ticker, error=error)


# ═══════════════════════════════════════════
#  PROFIT STATEMENT
# ═══════════════════════════════════════════
@app.route('/profit_statement', methods=['GET', 'POST'])
def profit_statement():
    fin_data = None; result = None; ticker = ""; error = None
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').strip()
        try:
            if ticker:
                fin_data = get_full_financials(ticker)
                if fin_data["ok"]:
                    rev = (fin_data["income"]["rev_0"] or 0) * 1e7
                    ni  = (fin_data["income"]["ni_0"]  or 0) * 1e7
                else:
                    error = fin_data.get("error")
            else:
                rev = float(request.form.get('revenue', 0))
                ni  = float(request.form.get('net_income', 0))
            if not error:
                margin = round(ni/rev*100, 2) if rev else 0
                result = {
                    "revenue": rev, "net_income": ni, "margin": margin,
                    "margin_tag": (
                        "High" if margin>=20 else "Moderate" if margin>=10
                        else "Low" if margin>=0 else "Loss-Making"),
                }
        except Exception as e:
            error = str(e)
    return render_template('profit_statement.html',
        fin_data=fin_data, result=result, ticker=ticker, error=error)


# ═══════════════════════════════════════════
#  RATIO ANALYSIS
# ═══════════════════════════════════════════
@app.route('/ratio_analysis', methods=['GET', 'POST'])
def ratio_analysis():
    fin_data = None; result = None; ticker = ""; error = None
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').strip()
        try:
            if ticker:
                fin_data = get_full_financials(ticker)
                if fin_data["ok"]:
                    result = {**fin_data["ratios"], **fin_data["scores"]}
                    result["insights"] = fin_data["insights"]
                    result["flags"]    = fin_data["flags"]
                else:
                    error = fin_data.get("error")
            else:
                ca  = float(request.form.get('current_assets', 0))
                cl  = float(request.form.get('current_liabilities', 0))
                eq  = float(request.form.get('equity', 0))
                tl  = float(request.form.get('liabilities', 0))
                ni  = float(request.form.get('net_income', 0))
                rev = float(request.form.get('revenue', 0))
                result = {
                    "current_ratio": round(ca/cl,2)      if cl  else None,
                    "de_ratio":      round(tl/eq,2)      if eq  else None,
                    "net_margin":    round(ni/rev*100,2) if rev else None,
                }
        except Exception as e:
            error = str(e)
    return render_template('ratio_analysis.html',
        fin_data=fin_data, result=result, ticker=ticker, error=error)


# ═══════════════════════════════════════════
#  RESEARCH REPORT
# ═══════════════════════════════════════════
@app.route('/research-report', methods=['GET', 'POST'])
def research_report():
    data = None; ticker = ""; error = None
    ticker = request.form.get('ticker', request.args.get('ticker', '')).strip()
    if ticker:
        data = generate_research_report(ticker)
        if not data.get("ok"):
            error = data.get("error", "Could not generate report")
            data  = None
        else:
            # Add financial tables to report
            data["fin_tables"] = _get_financial_tables(ticker)
    return render_template('research_report.html',
        data=data, ticker=ticker, error=error)


# ═══════════════════════════════════════════
#  COMPARE
# ═══════════════════════════════════════════
@app.route('/compare', methods=['GET', 'POST'])
def compare():
    data = None; ticker1 = ""; ticker2 = ""; error = None
    ticker1 = request.form.get('ticker1', '').strip()
    ticker2 = request.form.get('ticker2', '').strip()
    if ticker1 and ticker2:
        data = compare_stocks(ticker1, ticker2)
        if not data["t1"].get("ok") or not data["t2"].get("ok"):
            error = "Could not load data for one or both tickers."
    return render_template('compare.html',
        data=data, ticker1=ticker1, ticker2=ticker2, error=error)

@app.route('/api/compare/<t1>/<t2>')
def api_compare(t1, t2):
    return jsonify(compare_stocks(t1, t2))

# ── Quant Hub Home ──────────────────────────────────────────
@app.route('/quant')
def quant():
    return render_template('quant.html')


# ── Signal Engine ───────────────────────────────────────────
@app.route('/quant/signals')
def quant_signals():
    return render_template('signals.html')


# ── Price Forecast ──────────────────────────────────────────
@app.route('/quant/forecast')
def quant_forecast():
    return render_template('forecast.html')


# ── Portfolio Optimizer + Correlation ──────────────────────
@app.route('/quant/optimizer')
@app.route('/quant/correlation')
def quant_optimizer():
    return render_template('optimizer.html')


# ── Risk Metrics Page ───────────────────────────────────────
@app.route('/quant/risk')
def quant_risk():
    return render_template('quant.html')    # uses the hub page's quick-risk widget


# ═══════════════════════════════════════════════════════════
#  JSON APIS
# ═══════════════════════════════════════════════════════════

@app.route('/api/quant/risk/<ticker>')
def api_quant_risk(ticker):
    period = request.args.get('period', '1y')
    return jsonify(get_risk_metrics(ticker, period))


@app.route('/api/quant/optimize', methods=['POST'])
def api_quant_optimize():
    data    = request.get_json() or {}
    tickers = data.get('tickers', [])
    period  = data.get('period', '1y')
    return jsonify(optimize_portfolio(tickers, period))


@app.route('/api/quant/signals', methods=['POST'])
def api_quant_signals():
    data    = request.get_json() or {}
    tickers = data.get('tickers', [])
    return jsonify(get_signals(tickers))


@app.route('/api/quant/forecast/<ticker>')
def api_quant_forecast(ticker):
    days = int(request.args.get('days', 30))
    return jsonify(get_forecast(ticker, days))


@app.route('/api/quant/correlation', methods=['POST'])
def api_quant_correlation():
    data    = request.get_json() or {}
    tickers = data.get('tickers', [])
    period  = data.get('period', '1y')
    return jsonify(get_correlation(tickers, period))


# ── AI Insight APIs ─────────────────────────────────────────
@app.route('/api/quant/insights/risk/<ticker>')
def api_insights_risk(ticker):
    period = request.args.get('period', '1y')
    risk   = get_risk_metrics(ticker, period)
    return jsonify(insights_from_risk(risk, ticker))


@app.route('/api/quant/insights/signal/<ticker>')
def api_insights_signal(ticker):
    signals = get_signals([ticker])
    if signals['ok'] and signals['signals']:
        return jsonify(insights_from_signal(signals['signals'][0]))
    return jsonify({'ok': False, 'error': 'No signal data'})


@app.route('/api/quant/insights/forecast/<ticker>')
def api_insights_forecast(ticker):
    days     = int(request.args.get('days', 30))
    forecast = get_forecast(ticker, days)
    return jsonify(insights_from_forecast(forecast))


# ── Export (Premium-locked in UI, backend ready) ────────────
@app.route('/api/export/<ticker>')
def api_export(ticker):
    """
    This endpoint is backend-ready but the UI button is locked
    with a 'Coming Soon' overlay. When you're ready to unlock,
    remove the overlay in quant.html and this route serves the CSV.
    """
    csv_data  = build_export_csv(ticker)
    from flask import Response
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=finflow_{ticker}_{__import__("datetime").date.today()}.csv'}
    )

# ═══════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════
if __name__ == '__main__':
    app.run(debug=True)
