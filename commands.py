import json
import os
from pathlib import Path

import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"
STATE_FILE = Path("state.json")
OFFSET_FILE = Path("telegram_offset.json")


def send_message(text):
    response = requests.post(
        f"{API}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")


def last_five():
    if not STATE_FILE.exists():
        return "Пока нет сохранённых данных мониторинга. Дождитесь первого запуска проверки."
    records = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    items = list(records.values())[:5]
    if not items:
        return "Пока нет сохранённых релизов."
    lines = ["Последние 5 версий 1С:Бухгалтерии для Казахстана 3.0:", ""]
    for item in items:
        version = item.get("version", "—")
        text = item.get("text", "")
        import re
        date = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", text)
        lines.append(f"• {version}" + (f" — {date.group(0)}" if date else ""))
        for label, url in item.get("links", []):
            if "дополн" in label.lower():
                lines.append(f"  Дополнения: {url}")
                break
        for label, url in item.get("links", []):
            if label == version:
                lines.append(f"  Релиз: {url}")
                break
        lines.append("")
    return "\n".join(lines).strip()


def main():
    offset = 0
    if OFFSET_FILE.exists():
        offset = int(json.loads(OFFSET_FILE.read_text(encoding="utf-8")).get("offset", 0))

    response = requests.get(
        f"{API}/getUpdates",
        params={"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message"])},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")

    updates = data.get("result", [])
    for update in updates:
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        command = (message.get("text") or "").strip().split()[0].lower() if message.get("text") else ""
        if chat_id == CHAT_ID and command in ("/last5", "/last5@buhkz30_monitor_bot"):
            send_message(last_five())
        elif chat_id == CHAT_ID and command == "/start":
            send_message("Мониторинг работает. Команда /last5 покажет пять последних версий 1С:Бухгалтерии для Казахстана 3.0.")

    if updates:
        new_offset = max(item["update_id"] for item in updates) + 1
        OFFSET_FILE.write_text(json.dumps({"offset": new_offset}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Обработано обновлений Telegram: {len(updates)}; offset: {new_offset}")
    else:
        print("Новых команд Telegram нет.")


if __name__ == "__main__":
    main()
