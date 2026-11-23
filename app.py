from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import requests, time, random, math

app = Flask(__name__, static_folder='static')
CORS(app)

KEY  = 'dbrat01r01qij0hik8o0dbrat01r01qij0hik8og'
BASE = 'https://finnhub.io/api/v1'
YQ1  = 'https://query1.finance.yahoo.com'
YQ2  = 'https://query2.finance.yahoo.com'
AV_KEY  = 'GEU20PRE83EUM693'
AV_BASE = 'https://www.alphavantage.co/query'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ── Helpers ──────────────────────────────────────────────────────────────

def fh(endpoint, params):
    params['token'] = KEY
    try:
        r = requests.get(f'{BASE}/{endpoint}', params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[FH ERROR] {endpoint}: {e}")
        return {}

INDIAN_INDICES = {'^NSEI', '^NSEBANK', '^BSESN', '^NSMIDCP', '^CNXIT'}

def is_indian(sym):
    s = sym.upper()
    return s.startswith('BSE:') or s.startswith('NSE:') or s.endswith('.BO') or s.endswith('.NS') or s in INDIAN_INDICES

def to_av_symbol(sym):
    """Convert NSE:/BSE: prefix to Alpha Vantage format (e.g. RELIANCE.BSE)"""
    s = sym.upper()
    if s.startswith('BSE:'):  return s[4:] + '.BSE'
    if s.startswith('NSE:'):  return s[4:] + '.NSE'
    return s

def av_quote(sym):
    """Fetch real-time quote from Alpha Vantage for Indian stocks"""
    av_sym = to_av_symbol(sym)
    try:
        r = requests.get(AV_BASE, params={
            'function': 'GLOBAL_QUOTE',
            'symbol': av_sym,
            'apikey': AV_KEY
        }, timeout=12)
        d = r.json().get('Global Quote', {})
        if not d or not d.get('05. price'):
            return None
        price = float(d.get('05. price', 0))
        prev  = float(d.get('08. previous close', price))
        chg   = float(d.get('09. change', 0))
        chgp  = float(d.get('10. change percent', '0%').replace('%',''))
        return {
            'c':  price,
            'pc': prev,
            'h':  float(d.get('03. high', price)),
            'l':  float(d.get('04. low',  price)),
            'd':  chg,
            'dp': chgp,
        }
    except Exception as e:
        print(f"[AV Quote ERROR] {sym}: {e}")
        return None

def av_candles(sym, outputsize='compact'):
    """Fetch daily candles from Alpha Vantage (compact=100 days)"""
    av_sym = to_av_symbol(sym)
    try:
        r = requests.get(AV_BASE, params={
            'function': 'TIME_SERIES_DAILY',
            'symbol': av_sym,
            'outputsize': outputsize,
            'apikey': AV_KEY
        }, timeout=15)
        d = r.json()
        ts_data = d.get('Time Series (Daily)', {})
        if not ts_data:
            print(f"[AV Candles] No data for {av_sym}: {list(d.keys())}")
            return None
        dates = sorted(ts_data.keys())[-90:]  # last 90 trading days
        t, o, h, l, c, v = [], [], [], [], [], []
        for date in dates:
            row = ts_data[date]
            dt = int(time.mktime(time.strptime(date, '%Y-%m-%d')))
            t.append(dt)
            o.append(float(row['1. open']))
            h.append(float(row['2. high']))
            l.append(float(row['3. low']))
            c.append(float(row['4. close']))
            v.append(int(row['5. volume']))
        return {'s': 'ok', 't': t, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v}
    except Exception as e:
        print(f"[AV Candles ERROR] {sym}: {e}")
        return None

def av_search(keywords):
    """Search for Indian stocks by keyword"""
    try:
        r = requests.get(AV_BASE, params={
            'function': 'SYMBOL_SEARCH',
            'keywords': keywords,
            'apikey': AV_KEY
        }, timeout=10)
        matches = r.json().get('bestMatches', [])
        # Filter for Indian exchanges
        indian = [m for m in matches if 'BSE' in m.get('4. region','') or 'NSE' in m.get('4. region','') or '.BSE' in m.get('1. symbol','') or '.NSE' in m.get('1. symbol','')]
        return indian[:5]
    except Exception as e:
        print(f"[AV Search ERROR] {keywords}: {e}")
        return []

def to_yahoo(sym):
    """Convert any symbol format to Yahoo Finance ticker"""
    s = sym.upper()
    if s.startswith('BSE:'):   return s[4:] + '.BO'
    if s.startswith('NSE:'):   return s[4:] + '.NS'
    # Crypto: BINANCE:BTCUSDT -> BTC-USD
    if s.startswith('BINANCE:'):
        pair = s[8:]  # BTCUSDT
        if pair.endswith('USDT'): return pair[:-4] + '-USD'
        if pair.endswith('USD'):  return pair[:-3] + '-USD'
        return pair
    # Forex: OANDA:EUR_USD -> EURUSD=X
    if s.startswith('OANDA:'):
        pair = s[6:].replace('_','')
        return pair + '=X'
    return s   # US stocks: AAPL, TSLA etc.

def yahoo_chart(ticker, period='3mo', interval='1d'):
    """Fetch OHLCV from Yahoo Finance chart API"""
    url = f'{YQ1}/v8/finance/chart/{ticker}'
    params = {'period1': int(time.time()) - 180*86400,
              'period2': int(time.time()),
              'interval': interval,
              'range': period}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=12)
        data = r.json()
        result = data['chart']['result'][0]
        meta   = result['meta']
        timestamps = result.get('timestamp', [])
        q = result['indicators']['quote'][0]
        closes  = q.get('close',  [])
        opens   = q.get('open',   [])
        highs   = q.get('high',   [])
        lows    = q.get('low',    [])
        volumes = q.get('volume', [])
        # Remove None values
        valid = [(t,o,h,l,c,v) for t,o,h,l,c,v in
                 zip(timestamps,opens,highs,lows,closes,volumes)
                 if c is not None]
        if not valid:
            return None, meta
        ts,o,h,l,c,v = zip(*valid)
        return {'t':list(ts),'o':list(o),'h':list(h),'l':list(l),
                'c':list(c),'v':list(v),'s':'ok'}, meta
    except Exception as e:
        print(f"[Yahoo Chart ERROR] {ticker}: {e}")
        return None, {}

def yahoo_quote_from_meta(meta, candles):
    """Build a quote dict from Yahoo meta + candle data"""
    price = meta.get('regularMarketPrice') or (candles['c'][-1] if candles else 0)
    prev  = meta.get('chartPreviousClose') or meta.get('previousClose') or price
    return {
        'c':  price,
        'pc': prev,
        'h':  meta.get('regularMarketDayHigh', price),
        'l':  meta.get('regularMarketDayLow',  price),
        'd':  round(price - prev, 4),
        'dp': round((price - prev) / prev * 100, 2) if prev else 0,
    }

def yahoo_profile_data(ticker, sym):
    """Fetch company profile from Yahoo quoteSummary"""
    try:
        url = f'{YQ1}/v10/finance/quoteSummary/{ticker}'
        params = {'modules': 'assetProfile,summaryDetail'}
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        d = r.json()['quoteSummary']['result'][0]
        ap = d.get('assetProfile', {})
        sd = d.get('summaryDetail', {})
        mc = sd.get('marketCap', {})
        name = ap.get('longName') or ap.get('shortName') or sym
        return {
            'name': name,
            'exchange': ap.get('exchange', ''),
            'finnhubIndustry': ap.get('industry', ''),
            'marketCapitalization': mc.get('raw', 0) / 1e7 if mc else 0,
            'currency': sd.get('currency', 'USD'),
            'country':  ap.get('country', ''),
            'weburl':   ap.get('website', ''),
        }
    except Exception as e:
        print(f"[Yahoo Profile ERROR] {ticker}: {e}")
        bare = sym.replace('BSE:','').replace('NSE:','').replace('BINANCE:','').replace('OANDA:','')
        return {'name': bare, 'exchange':'', 'finnhubIndustry':'',
                'marketCapitalization':0, 'currency':'USD'}

def simulated_candles(current, prev, sym, n=60):
    """Fallback: generate realistic history anchored to real price"""
    random.seed(hash(sym) % 10000)
    closes, price = [], current * 0.85
    for i in range(n):
        drift  = (current - price) / (n - i + 1)
        change = drift + random.gauss(0, current * 0.012)
        price  = max(price + change, 0.0001)
        closes.append(round(price, 6))
    closes[-1] = current
    closes[-2] = prev
    t_now = int(time.time())
    ts   = [t_now - (n-1-i)*86400 for i in range(n)]
    highs = [round(c*(1+abs(random.gauss(0,0.008))),6) for c in closes]
    lows  = [round(c*(1-abs(random.gauss(0,0.008))),6) for c in closes]
    opens = [closes[i-1] if i>0 else closes[0] for i in range(n)]
    vols  = [int(random.uniform(1_000_000,50_000_000)) for _ in closes]
    return {'s':'ok','t':ts,'o':opens,'h':highs,'l':lows,'c':closes,'v':vols}

# ── Routes ───────────────────────────────────────────────────────────────

@app.route('/api/quote')
def quote():
    sym = request.args.get('symbol','SPY').upper()
    # Indian stocks: try Alpha Vantage first (but skip for indices like ^NSEI)
    if is_indian(sym) and not sym.startswith('^'):
        avq = av_quote(sym)
        if avq and avq.get('c'):
            print(f"[quote] {sym} → Alpha Vantage ✅")
            return jsonify(avq)
        # Fallback to Yahoo
        print(f"[quote] {sym} → AV failed, trying Yahoo")
    ytick = to_yahoo(sym)
    print(f"[quote] {sym} → Yahoo {ytick}")
    candles, meta = yahoo_chart(ytick, period='5d', interval='1d')
    if meta and meta.get('regularMarketPrice'):
        return jsonify(yahoo_quote_from_meta(meta, candles))
    # Fallback to Finnhub for US stocks
    fhq = fh('quote', {'symbol': sym})
    if fhq and fhq.get('c'):
        return jsonify(fhq)
    return jsonify({'c':0})

@app.route('/api/candles')
def candles_route():
    sym = request.args.get('symbol','SPY').upper()
    # Indian stocks: try Alpha Vantage first (but skip indices like ^NSEI)
    if is_indian(sym) and not sym.startswith('^'):
        avc = av_candles(sym)
        if avc and len(avc.get('c',[])) >= 10:
            print(f"[candles] {sym} → Alpha Vantage ✅ {len(avc['c'])} days")
            return jsonify(avc)
        print(f"[candles] {sym} → AV failed, trying Yahoo")
    ytick = to_yahoo(sym)
    print(f"[candles] {sym} → Yahoo {ytick}")
    candle_data, meta = yahoo_chart(ytick, period='3mo', interval='1d')
    if candle_data and len(candle_data['c']) >= 10:
        print(f"[candles] ✅ Real data: {len(candle_data['c'])} days")
        return jsonify(candle_data)
    # Fallback: use Finnhub quote + simulate
    print(f"[candles] ⚠️ Yahoo failed, using simulated candles for {sym}")
    fhq = fh('quote', {'symbol': sym})
    current = (fhq.get('c') or 0) if fhq else 0
    if not current and meta:
        current = meta.get('regularMarketPrice', 0)
    if not current:
        return jsonify({'s':'no_data'})
    prev = (fhq.get('pc') or current*0.99) if fhq else current*0.99
    return jsonify(simulated_candles(current, prev, sym))

@app.route('/api/profile')
def profile():
    sym   = request.args.get('symbol','SPY').upper()
    # Indian stocks: return basic profile
    if is_indian(sym):
        bare = sym.replace('BSE:','').replace('NSE:','')
        # Known Indian company/index names
        INDIAN_NAMES = {
            '^NSEI':'Nifty 50 Index','^NSEBANK':'Nifty Bank Index',
            '^BSESN':'BSE Sensex','^CNXIT':'Nifty IT Index',
            'RELIANCE':'Reliance Industries','TCS':'Tata Consultancy Services',
            'INFY':'Infosys Ltd','HDFCBANK':'HDFC Bank','ICICIBANK':'ICICI Bank',
            'HINDUNILVR':'Hindustan Unilever','ITC':'ITC Ltd','SBIN':'State Bank of India',
            'BHARTIARTL':'Bharti Airtel','WIPRO':'Wipro Ltd','AXISBANK':'Axis Bank',
            'KOTAKBANK':'Kotak Mahindra Bank','LT':'Larsen & Toubro','ASIANPAINT':'Asian Paints',
            'MARUTI':'Maruti Suzuki','TITAN':'Titan Company','SUNPHARMA':'Sun Pharmaceutical',
            'ULTRACEMCO':'UltraTech Cement','NESTLEIND':'Nestle India','BAJFINANCE':'Bajaj Finance',
            'POWERGRID':'Power Grid Corp','NTPC':'NTPC Ltd','ONGC':'ONGC Ltd',
            'JSWSTEEL':'JSW Steel','TATASTEEL':'Tata Steel','ADANIENT':'Adani Enterprises',
            'ADANIPORTS':'Adani Ports','DRREDDY':'Dr Reddy\'s Labs','CIPLA':'Cipla Ltd',
        }
        name = INDIAN_NAMES.get(sym, INDIAN_NAMES.get(bare, bare))
        exch = 'NSE' if sym.startswith('^NSE') or sym.startswith('NSE:') else ('BSE' if sym.startswith('BSE:') else 'NSE')
        industry = 'NSE Index' if sym.startswith('^') else 'Indian Market'
        return jsonify({'name': name, 'exchange': exch, 'finnhubIndustry': industry,
                        'marketCapitalization': 0, 'currency': 'INR', 'country': 'India'})
    ytick = to_yahoo(sym)
    print(f"[profile] {sym} → Yahoo {ytick}")
    yp = yahoo_profile_data(ytick, sym)
    if yp.get('name') and yp['name'] != sym:
        return jsonify(yp)
    return jsonify(fh('stock/profile2', {'symbol': sym}))

@app.route('/api/india/search')
def india_search():
    """Search for Indian stocks by name"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    results = av_search(q)
    return jsonify(results)

@app.route('/api/options')
def options_route():
    """Fetch real options chain from Yahoo Finance (US stocks only)."""
    sym   = request.args.get('symbol', 'AAPL').upper()
    if is_indian(sym):
        return jsonify({'error': 'Options not available for Indian stocks', 'ticker': sym})
    ytick = to_yahoo(sym)
    print(f"[options] {sym} → Yahoo {ytick}")

    try:
        # 1. Get available expiry dates
        url_dates = f'{YQ1}/v7/finance/options/{ytick}'
        r = requests.get(url_dates, headers=HEADERS, timeout=12)
        data = r.json()
        result = data.get('optionChain', {}).get('result', [])
        if not result:
            return jsonify({'error': 'No options data', 'ticker': ytick})

        meta      = result[0].get('meta', {})
        spot      = meta.get('regularMarketPrice', 0)
        all_dates = result[0].get('expirationDates', [])  # Unix timestamps

        if not all_dates:
            return jsonify({'error': 'No expiry dates', 'spot': spot})

        # 2. Pick the nearest 3 expiries (weekly/monthly)
        now = int(time.time())
        future_dates = sorted([d for d in all_dates if d > now])[:3]
        if not future_dates:
            future_dates = sorted(all_dates)[:3]

        chains = []
        for expiry_ts in future_dates:
            url_chain = f'{YQ1}/v7/finance/options/{ytick}?date={expiry_ts}'
            rc = requests.get(url_chain, headers=HEADERS, timeout=10)
            cd = rc.json()
            cr = cd.get('optionChain', {}).get('result', [])
            if not cr:
                continue
            opts = cr[0].get('options', [{}])[0]
            calls_raw = opts.get('calls', [])
            puts_raw  = opts.get('puts', [])

            # Find ATM ± 10% strikes
            def filter_near(opts_list, spot_p, pct=0.10):
                lo, hi = spot_p * (1 - pct), spot_p * (1 + pct)
                return [o for o in opts_list if lo <= o.get('strike', 0) <= hi]

            calls = filter_near(calls_raw, spot)
            puts  = filter_near(puts_raw,  spot)

            def summarize_opts(opts_list):
                out = []
                for o in opts_list[:6]:  # max 6 strikes per side
                    out.append({
                        'strike':       o.get('strike', 0),
                        'lastPrice':    o.get('lastPrice', 0),
                        'bid':          o.get('bid', 0),
                        'ask':          o.get('ask', 0),
                        'impliedVol':   round(o.get('impliedVolatility', 0) * 100, 1),
                        'delta':        round(o.get('delta', 0), 3) if o.get('delta') else None,
                        'theta':        round(o.get('theta', 0), 4) if o.get('theta') else None,
                        'openInterest': o.get('openInterest', 0),
                        'volume':       o.get('volume', 0),
                        'inTheMoney':   o.get('inTheMoney', False),
                    })
                return out

            expiry_label = time.strftime('%b %d, %Y', time.gmtime(expiry_ts))
            days_to_exp  = max(1, (expiry_ts - now) // 86400)

            chains.append({
                'expiry':     expiry_label,
                'expiryTs':   expiry_ts,
                'daysToExp':  days_to_exp,
                'calls':      summarize_opts(calls),
                'puts':       summarize_opts(puts),
            })

        # 3. Put/Call ratio from nearest expiry
        pc_ratio = None
        if chains:
            c_oi = sum(o['openInterest'] for o in chains[0]['calls'])
            p_oi = sum(o['openInterest'] for o in chains[0]['puts'])
            pc_ratio = round(p_oi / c_oi, 2) if c_oi else None

        return jsonify({
            'spot':     spot,
            'ticker':   ytick,
            'pcRatio':  pc_ratio,
            'chains':   chains,
        })

    except Exception as e:
        print(f"[Options ERROR] {sym}: {e}")
        return jsonify({'error': str(e), 'ticker': ytick})


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    print('\n🚀 Trading Bot — Yahoo Finance + Alpha Vantage (Indian Stocks) + Finnhub\n')
    app.run(port=5000, debug=True)
