import os
import urllib.parse
import urllib.request


CHAT_ID = "1560838491"


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("❌ Δεν βρέθηκε TELEGRAM_BOT_TOKEN")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
    }).encode()

    try:
        request = urllib.request.Request(
            url,
            data=data,
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            result = response.read().decode()

        if '"ok":true' in result:
            return True

        print("❌ Telegram error:", result)
        return False

    except Exception as e:
        print("❌ Telegram error:", e)
        return False
