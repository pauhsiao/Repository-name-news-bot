 import os
  import feedparser
  import anthropic
  import requests
  from datetime import datetime, timezone

  RSS_FEEDS = [
      ("Reuters", "https://feeds.reuters.com/reuters/topNews"),
      ("AP News", "https://feeds.apnews.com/rss/apf-topnews"),
      ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
      ("BBC Chinese", "https://feeds.bbci.co.uk/zhongwen/trad/rss.xml"),
      ("CNN", "http://rss.cnn.com/rss/edition.rss"),
      ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
      ("NPR", "https://feeds.npr.org/1001/rss.xml"),
      ("The Guardian", "https://www.theguardian.com/world/rss"),
      ("DW", "https://rss.dw.com/xml/rss-en-all"),
      ("France 24", "https://www.france24.com/en/rss"),
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
          prompt = f"""你是一位專業的新聞編輯。以下是今天來自全球10大新聞網的新聞。
  請篩選出 5-8 則最重要的全球重大新聞，用繁體中文整理成每日摘要。

  格式：
  📰 今日全球重大新聞
  {today}
  ━━━━━━━━━━━━━━━

  1️[標題]（來源）
  [2-3句重點說明]

  2️...

  ━━━━━━━━━━━━━━━
  📌 [一句話總結今日全球局勢]

  新聞資料：
  {articles_text}"""
      else:
          prompt = f"""你是一位突發新聞編輯。以下是最新的全球新聞。
  請判斷是否有真正的突發重大新聞（重大天災、戰爭重大進展、重要領導人死亡、嚴重金融危機、重大恐怖攻擊等）。

  如果有，用繁體中文回覆：
  🚨 突發重大新聞
  ━━━━━━━━━━━━━━━
  [標題]（來源）
  [3-4句重點說明]

  如果沒有突發重大新聞，只回覆：NONE

  新聞資料：
  {articles_text}"""

      message = client.messages.create(
          model="claude-haiku-4-5-20251001",
          max_tokens=1500,
          messages=[{"role": "user", "content": prompt}]
      )
      return message.content[0].text.strip()

  def send_line_message(text):
      response = requests.post(
          "https://api.line.me/v2/bot/message/push",
          headers={
              "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
              "Content-Type": "application/json",
          },
          json={
              "to": os.environ["LINE_USER_ID"],
              "messages": [{"type": "text", "text": text}],
          },
      )
      print(f"LINE API: {response.status_code}")
      return response.ok

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
