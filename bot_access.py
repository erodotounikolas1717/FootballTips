import os
import json
import urllib.parse
import urllib.request

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USERS_FILE = "users.json"


def telegram(method, data=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    if data:
        encoded = urllib.parse.urlencode(data).encode()
        request = urllib.request.Request(url, data=encoded, method="POST")
    else:
        request = urllib.request.Request(url)

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def load_users():
    if not os.path.exists(USERS_FILE):
        return {
            "pending": [],
            "approved": []
        }

    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"pending": [], "approved": []}

        data.setdefault("pending", [])
        data.setdefault("approved", [])

        return data

    except Exception:
        return {
            "pending": [],
            "approved": []
        }


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def request_access(user):
    users = load_users()

    user_id = str(user["id"])

    if user_id in [str(x) for x in users["approved"]]:
        return "✅ Είσαι ήδη εγκεκριμένος χρήστης."


    if any(str(x.get("id")) == user_id for x in users["pending"]):
        return "⏳ Το αίτημά σου έχει ήδη σταλεί. Περιμένουμε έγκριση."


    user_info = {
        "id": user["id"],
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", "")
    }

    users["pending"].append(user_info)
    save_users(users)

    username = (
        f"@{user_info['username']}"
        if user_info["username"]
        else "χωρίς username"
    )

    message = (
        "📩 <b>ΝΕΟ REQUEST ACCESS</b>\n\n"
        f"👤 Όνομα: {user_info['first_name']} {user_info['last_name']}\n"
        f"📱 Username: {username}\n"
        f"🆔 ID: {user_info['id']}\n\n"
        "Θέλεις να εγκρίνεις αυτόν τον χρήστη;"
    )

    keyboard = json.dumps({
        "inline_keyboard": [[
            {
                "text": "✅ ACCEPT",
                "callback_data": f"accept:{user_id}"
            },
            {
                "text": "❌ REJECT",
                "callback_data": f"reject:{user_id}"
            }
        ]]
    })

    telegram(
        "sendMessage",
        {
            "chat_id": ADMIN_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "reply_markup": keyboard
        }
    )

    return (
        "📩 Το αίτημά σου στάλθηκε!\n\n"
        "⏳ Περιμένουμε την έγκρισή σου από τον διαχειριστή."
    )


def handle_callback(callback):
    data = callback.get("data", "")
    callback_id = callback.get("id")

    if not data.startswith(("accept:", "reject:")):
        return

    if str(callback.get("message", {}).get("chat", {}).get("id")) != str(ADMIN_CHAT_ID):
        return

    action, user_id = data.split(":", 1)

    users = load_users()

    pending_user = None

    for user in users["pending"]:
        if str(user.get("id")) == user_id:
            pending_user = user
            break

    if pending_user is None:
        telegram(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
                "text": "Ο χρήστης δεν βρέθηκε."
            }
        )
        return

    users["pending"] = [
        user for user in users["pending"]
        if str(user.get("id")) != user_id
    ]

    if action == "accept":
        if user_id not in [str(x) for x in users["approved"]]:
            users["approved"].append(user_id)

        save_users(users)

        telegram(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    "🎉 <b>ΕΓΚΡΙΘΗΚΕΣ!</b>\n\n"
                    "✅ Έχεις πλέον πρόσβαση στα Football Tips.\n"
                    "⚽ Καλώς ήρθες!"
                ),
                "parse_mode": "HTML"
            }
        )

        telegram(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
                "text": "✅ Ο χρήστης εγκρίθηκε."
            }
        )

    else:
        save_users(users)

        telegram(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    "❌ Το αίτημά σου δεν εγκρίθηκε αυτή τη στιγμή."
                )
            }
        )

        telegram(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
                "text": "❌ Το request απορρίφθηκε."
            }
        )


def send_menu(chat_id):
    keyboard = json.dumps({
        "inline_keyboard": [[
            {
                "text": "📩 REQUEST ACCESS",
                "callback_data": "request_access"
            }
        ]]
    })

    telegram(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": (
                "🔥 <b>FOOTBALL TIPS</b>\n\n"
                "Καλώς ήρθες!\n\n"
                "Για να ζητήσεις δωρεάν πρόσβαση,\n"
                "πάτησε το κουμπί:"
            ),
            "parse_mode": "HTML",
            "reply_markup": keyboard
        }
    )


def main():
    print("🤖 Football Tips Access Bot started...")

    offset = 0

    while True:
        result = telegram(
            "getUpdates",
            {
                "offset": offset,
                "timeout": 25
            }
        )

        for update in result.get("result", []):
            offset = update["update_id"] + 1

            if "message" in update:
                message = update["message"]
                text = message.get("text", "")

                if text == "/start":
                    send_menu(message["chat"]["id"])

            elif "callback_query" in update:
                callback = update["callback_query"]

                if callback.get("data") == "request_access":
                    user = callback.get("from", {})
                    response = request_access(user)

                    telegram(
                        "answerCallbackQuery",
                        {
                            "callback_query_id": callback["id"],
                            "text": response[:200]
                        }
                    )

                    telegram(
                        "sendMessage",
                        {
                            "chat_id": user["id"],
                            "text": response,
                            "parse_mode": "HTML"
                        }
                    )

                else:
                    handle_callback(callback)


if __name__ == "__main__":
    main()
