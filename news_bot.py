import os
import json
import hashlib
import feedparser
import anthropic
import requests
from datetime import datetime, timezone

RSS_FEEDS = [
    # 國際新聞
    ("Reuters", "https://feeds.reuters.com/reuters/topNews"),
    ("AP News", "https://feeds.apnews.com/rss/apf-topnews"),
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Chinese", "https://feeds.bbci.co.uk/zhongwen/trad/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
    # 財經
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcombined/rss?partnerId=wrss01&id=10001147"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    # 科技
    ("Reuters Tech", "https://feeds.reuters.com/reuters/technologyNews"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
]

def hash_title(title):
    return hashlib.md5(title.encode()).hexdigest()

def load_seen():
    import base64
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return set(), None
    url = f"https://api.github.com/repos/{repo}/contents/seen_news.json"
    r = requests.get(url, headers={"Authorization": f"token {token}"})
    if r.status_code == 200:
        content = base64.b64decode(r.json()["content"]).decode()
        return set(json.loads(content)), r.json()["sha"]
    return set(), None

def save_seen(seen, sha):
    import base64
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return
    content = base64.b64encode(json.dumps(list(seen)[-500:]).encode()).decode()
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
    prompt = f"""以下是台灣股市近{days}個交易日成交量前10名的熱門股票：

{stocks_text}

請用繁體中文分析，格式如下：

📈 台股熱門股分析（近{days}日）
━━━━━━━━━━━━━━━
🔥 前5大熱門股：
1. [代號 名稱] - 收盤$[價] [漲跌]
   原因分析：[為何成交量大，可能的市場關注點]

2. ...

💡 今日操作建議：
[根據熱門股和市場情況，給出2-3點實用的操作方向]

━━━━━━━━━━━━━━━
⚠️ 以上為參考資訊，投資有風險，請謹慎評估"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
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
        prompt = "你是一位專業的財經新聞編輯，讀者是投資人。以下是今天來自全球各大新聞網的新聞，涵蓋國際、財經、科技三大類。\n請用繁體中文整理成每日摘要，格式如下：\n\n📰 今日重要資訊\n" + today + "\n━━━━━━━━━━━━━━━\n🌍 全球要聞（2-3則）\n1️⃣ [標題]（來源）\n[重點說明]\n\n💰 財經市場（2-3則，優先選對投資有影響的）\n1️⃣ [標題]（來源）\n[重點說明，說明對市場/投資的潛在影響]\n\n💻 科技動態（1-2則，優先選影響產業趨勢的）\n1️⃣ [標題]（來源）\n[重點說明]\n\n━━━━━━━━━━━━━━━\n📌 今日投資關注重點：[一句話總結今天最值得投資人注意的事]\n\n新聞資料：\n" + articles_text
    else:
        prompt = "你是一位突發新聞編輯。以下是最新的全球新聞。\n請判斷是否有真正的突發重大新聞（重大天災、戰爭重大進展、重要領導人死亡、嚴重金融危機、重大恐怖攻擊等）。\n\n如果有，用繁體中文回覆：\n🚨 突發重大新聞\n━━━━━━━━━━━━━━━\n[標題]（來源）\n[3-4句重點說明]\n\n如果沒有突發重大新聞，只回覆：NONE\n\n新聞資料：\n" + articles_text
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
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

def main():
    mode = os.environ.get("MODE", "daily")
    print(f"Mode: {mode}")
    articles = fetch_news()
    print(f"Fetched {len(articles)} articles")

    if mode == "breaking":
        seen, sha = load_seen()
        new_articles = [a for a in articles if hash_title(a["title"]) not in seen]
        if not new_articles:
            print("No new articles")
            return
        seen.update(hash_title(a["title"]) for a in new_articles)
        save_seen(seen, sha)
        articles = new_articles
        print(f"{len(articles)} new articles to check")

    result = analyze_with_claude(articles, mode)
    if mode == "breaking" and result == "NONE":
        print("No breaking news")
        return

    if mode == "daily":
        try:
            top_stocks, days = get_taiwan_stocks()
            if top_stocks:
                stock_report = analyze_taiwan_stocks(top_stocks, days)
                send_line_message(result)
                send_line_message(stock_report)
                print("Done with stocks!")
                return
        except Exception as e:
            print(f"Stock error: {e}")

    send_line_message(result)
    print("Done!")

if __name__ == "__main__":
    main()
