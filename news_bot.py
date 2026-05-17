import os
import json
import re
import hashlib
import feedparser
import anthropic
import requests
from datetime import datetime, timezone, timedelta

RSS_FEEDS = [
    # 國際綜合
    ("Reuters", "https://feeds.reuters.com/reuters/topNews"),
    ("AP News", "https://feeds.apnews.com/rss/apf-topnews"),
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Chinese", "https://feeds.bbci.co.uk/zhongwen/trad/rss.xml"),
    ("CNN", "http://rss.cnn.com/rss/edition.rss"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("France 24", "https://www.france24.com/en/rss"),
    ("DW", "https://rss.dw.com/xml/rss-en-all"),
    ("NYT", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    ("Washington Post", "https://feeds.washingtonpost.com/rss/world"),
    # 財經
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
    ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcombined/rss?partnerId=wrss01&id=10001147"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("WSJ", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    # 科技
    ("Reuters Tech", "https://feeds.reuters.com/reuters/technologyNews"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("Wired", "https://www.wired.com/feed/rss"),
]

_PREFIX_RE = re.compile(r'^(breaking|update|exclusive|developing|just in|alert|urgent)[:\s\-]+', re.IGNORECASE)

def hash_title(title):
    normalized = _PREFIX_RE.sub('', title).lower()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.md5(normalized.encode()).hexdigest()

def load_seen():
    import base64
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return {}, None
    url = f"https://api.github.com/repos/{repo}/contents/seen_news.json"
    r = requests.get(url, headers={"Authorization": f"token {token}"})
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if r.status_code == 200:
        raw = base64.b64decode(r.json()["content"]).decode()
        data = json.loads(raw)
        if isinstance(data, list):
            data = {h: "1970-01-01T00:00:00+00:00" for h in data}
        seen = {h: ts for h, ts in data.items() if ts >= cutoff}
        return seen, r.json()["sha"]
    return {}, None

def save_seen(seen, sha):
    import base64
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return
    if len(seen) > 500:
        seen = dict(sorted(seen.items(), key=lambda x: x[1], reverse=True)[:500])
    content = base64.b64encode(json.dumps(seen).encode()).decode()
    payload = {"message": "Update seen news", "content": content}
    if sha:
        payload["sha"] = sha
    requests.put(
        f"https://api.github.com/repos/{repo}/contents/seen_news.json",
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        json=payload,
    )

def get_taiwan_stocks():
    from datetime import timedelta
    headers = {"User-Agent": "Mozilla/5.0"}
    stock_totals = {}
    days_found = 0
    today = datetime.now(timezone.utc)

    for i in range(1, 12):
        if days_found >= 5:
            break
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        date_str = d.strftime("%Y%m%d")
        try:
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
            r = requests.get(url, headers=headers, timeout=15)
            data = r.json()
            if data.get("stat") != "OK":
                continue
            days_found += 1
            for table in data.get("tables", []):
                fields = table.get("fields", [])
                if not fields or "成交股數" not in str(fields):
                    continue
                for row in table.get("data", []):
                    if len(row) < 9:
                        continue
                    try:
                        code = row[0].strip()
                        name = row[1].strip()
                        vol = int(row[2].replace(",", ""))
                        close = row[8].replace(",", "")
                        change = row[10].replace(",", "") if len(row) > 10 else "-"
                        if code not in stock_totals:
                            stock_totals[code] = {"name": name, "vol": 0, "close": close, "change": change}
                        stock_totals[code]["vol"] += vol
                    except:
                        continue
                break
        except Exception as e:
            print(f"TWSE error {date_str}: {e}")

    top = sorted(stock_totals.items(), key=lambda x: x[1]["vol"], reverse=True)[:10]
    return top, days_found

def analyze_taiwan_stocks(top_stocks, days):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    stocks_text = "\n".join([
        f"{code} {info['name']} | 近{days}日總量:{info['vol']:,} | 收盤:{info['close']} | 漲跌:{info['change']}"
        for code, info in top_stocks
    ])
    prompt = f"""台灣股市近{days}交易日成交量前10名：

{stocks_text}

用繁體中文極簡格式回覆，列出前5檔，每檔一行：

📈 台股速報
─────────
🔥 [代號 名稱] $[收盤] [漲跌] — [原因10字內]
🔥 [代號 名稱] $[收盤] [漲跌] — [原因10字內]
🔥 [代號 名稱] $[收盤] [漲跌] — [原因10字內]
🔥 [代號 名稱] $[收盤] [漲跌] — [原因10字內]
🔥 [代號 名稱] $[收盤] [漲跌] — [原因10字內]
💡 [操作建議15字內]
⚠️ 投資有風險"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

def get_us_stocks(articles):
    import yfinance as yf

    indices = {"S&P500": "^GSPC", "納斯達克": "^IXIC", "道瓊": "^DJI"}
    popular = ["AAPL","MSFT","NVDA","TSLA","META","AMZN","GOOGL","AMD","NFLX","PLTR","TSM","BABA"]

    indices_text = []
    for name, sym in indices.items():
        try:
            hist = yf.Ticker(sym).history(period="2d")
            if len(hist) >= 2:
                close = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                chg = (close - prev) / prev * 100
                arrow = "▲" if chg > 0 else "▼"
                indices_text.append(f"{name}: {close:,.0f} {arrow}{abs(chg):.2f}%")
        except:
            pass

    stocks = []
    for sym in popular:
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if not hist.empty:
                vol = int(hist["Volume"].sum())
                close = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2] if len(hist) > 1 else close
                chg = (close - prev) / prev * 100
                stocks.append({"symbol": sym, "vol": vol, "close": close, "change": chg})
        except:
            pass

    stocks.sort(key=lambda x: x["vol"], reverse=True)

    trump_news = [a for a in articles if "trump" in (a["title"] + a["summary"]).lower()]

    return indices_text, stocks[:8], trump_news

def analyze_us_stocks(indices_text, stocks, trump_news):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    indices_str = " | ".join(indices_text) if indices_text else "資料暫無"
    stocks_str = "\n".join([
        f"{s['symbol']} | 近5日總量:{s['vol']:,} | 收盤:${s['close']:.2f} | 漲跌:{'+' if s['change']>0 else ''}{s['change']:.2f}%"
        for s in stocks
    ])
    trump_str = "\n".join([f"[{a['source']}] {a['title']}: {a['summary']}" for a in trump_news[:5]]) if trump_news else "今日無相關言論"

    prompt = f"""根據以下資料用繁體中文極簡回覆，列出前5檔熱門股，每檔一行：

大盤：{indices_str}
熱門股：{stocks_str}
川普新聞：{trump_str}

格式：

🇺🇸 美股速報
─────────
📊 [大盤數據一行]
🔥 [代號] $[收盤] [漲跌%] — [原因10字內]
🔥 [代號] $[收盤] [漲跌%] — [原因10字內]
🔥 [代號] $[收盤] [漲跌%] — [原因10字內]
🔥 [代號] $[收盤] [漲跌%] — [原因10字內]
🔥 [代號] $[收盤] [漲跌%] — [原因10字內]
🎙️ 川普：[一句影響，若無則省略此行]
💡 [操作建議15字內]
⚠️ 投資有風險"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

def fetch_news():
    articles = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                articles.append({
                    "source": source,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:300],
                })
        except Exception as e:
            print(f"Error fetching {source}: {e}")
    return articles

def analyze_with_claude(articles, mode):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    articles_text = "\n\n".join([
        f"[{a['source']}] {a['title']}\n{a['summary']}"
        for a in articles
    ])
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    if mode == "daily":
        prompt = ("以下是今天全球新聞，讀者是投資人。用繁體中文極簡格式回覆，規則：\n"
                  "- 每則新聞：標題（來源）— 重點15字內\n"
                  "- 全球要聞選2-3則，財經選2-3則，科技選1-2則\n"
                  "- 不要額外解釋，不要分段落說明\n\n"
                  "格式：\n"
                  "📰 今日速報 " + today + "\n"
                  "─────────\n"
                  "🌍 全球\n"
                  "· [標題]（來源）— [重點15字內]\n"
                  "· [標題]（來源）— [重點15字內]\n"
                  "💰 財經\n"
                  "· [標題]（來源）— [重點15字內]\n"
                  "· [標題]（來源）— [重點15字內]\n"
                  "💻 科技\n"
                  "· [標題]（來源）— [重點15字內]\n"
                  "📌 [一句總結，20字內]\n\n"
                  "新聞資料：\n" + articles_text)
    else:
        prompt = ("以下是最新全球新聞。判斷是否有真正的突發重大新聞（重大天災、戰爭重大進展、重要領導人死亡、嚴重金融危機、重大恐怖攻擊）。\n\n"
                  "若有，用繁體中文極簡回覆：\n"
                  "🚨 突發：[標題，20字內]\n"
                  "[2句重點，每句15字內]\n\n"
                  "若無，只回覆：NONE\n\n"
                  "新聞資料：\n" + articles_text)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

def send_line_message(text):
    response = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={
            "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
        json={"messages": [{"type": "text", "text": text}]},
    )
    print(f"LINE Broadcast: {response.status_code}")
    return response.ok

def check_daily_sent():
    """Return (already_sent_today, sha). Uses Taiwan time (UTC+8) as the day boundary."""
    import base64
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
    if not token or not repo:
        return False, None
    url = f"https://api.github.com/repos/{repo}/contents/last_daily.json"
    r = requests.get(url, headers={"Authorization": f"token {token}"})
    if r.status_code == 200:
        raw = base64.b64decode(r.json()["content"]).decode()
        data = json.loads(raw)
        return data.get("date") == today, r.json()["sha"]
    return False, None

def mark_daily_sent(sha):
    import base64
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
    if not token or not repo:
        return
    content = base64.b64encode(json.dumps({"date": today}).encode()).decode()
    payload = {"message": f"Daily sent {today}", "content": content}
    if sha:
        payload["sha"] = sha
    requests.put(
        f"https://api.github.com/repos/{repo}/contents/last_daily.json",
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        json=payload,
    )

def run_daily(articles=None):
    already_sent, daily_sha = check_daily_sent()
    if already_sent:
        print("Daily already sent today, skipping.")
        return
    mark_daily_sent(daily_sha)
    if articles is None:
        articles = fetch_news()
    result = analyze_with_claude(articles, "daily")
    send_line_message(result)
    try:
        top_stocks, days = get_taiwan_stocks()
        if top_stocks:
            send_line_message(analyze_taiwan_stocks(top_stocks, days))
    except Exception as e:
        print(f"Taiwan stock error: {e}")
    try:
        indices_text, us_stocks, trump_news = get_us_stocks(articles)
        if us_stocks:
            send_line_message(analyze_us_stocks(indices_text, us_stocks, trump_news))
    except Exception as e:
        print(f"US stock error: {e}")
    print("Daily done!")


def main():
    mode = os.environ.get("MODE", "daily")
    print(f"Mode: {mode}")

    if mode == "daily":
        run_daily()
        return

    articles = fetch_news()
    print(f"Fetched {len(articles)} articles")

    if mode == "breaking":
        # Fallback: if daily hasn't fired yet today and it's past 8am Taiwan time, send it now
        taiwan_hour = (datetime.now(timezone.utc) + timedelta(hours=8)).hour
        if taiwan_hour >= 8:
            run_daily(articles)

        seen, sha = load_seen()
        now_ts = datetime.now(timezone.utc).isoformat()
        new_articles = [a for a in articles if hash_title(a["title"]) not in seen]
        if not new_articles:
            print("No new articles")
            return
        for a in new_articles:
            seen[hash_title(a["title"])] = now_ts
        save_seen(seen, sha)
        articles = new_articles
        print(f"{len(articles)} new articles to check")

    result = analyze_with_claude(articles, mode)
    if mode == "breaking" and result == "NONE":
        print("No breaking news")
        return

    send_line_message(result)
    print("Done!")

if __name__ == "__main__":
    main()
