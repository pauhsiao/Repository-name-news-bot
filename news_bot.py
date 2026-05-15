import os
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
    user_ids = os.environ["LINE_USER_ID"].split(",")
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
    }
    for user_id in user_ids:
        user_id = user_id.strip()
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers,
            json={
                "to": user_id,
                "messages": [{"type": "text", "text": text}],
            },
        )
        print(f"LINE API {user_id}: {response.status_code}")
    return True

def main():
    mode = os.environ.get("MODE", "daily")
    print(f"Mode: {mode}")
    articles = fetch_news()
    print(f"Fetched {len(articles)} articles")
    result = analyze_with_claude(articles, mode)
    if mode == "breaking" and result == "NONE":
        print("No breaking news")
        return
    send_line_message(result)
    print("Done!")

if __name__ == "__main__":
    main()
