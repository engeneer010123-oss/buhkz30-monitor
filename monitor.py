import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PRODUCT_URL = "https://pro1c.kz/update/?PRODUCT_ID=2006"
HEADERS = {"User-Agent": "BuhKZ30Monitor/1.0 (GitHub Actions)"}
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "state.json"


def telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message[:3900],
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")


def fetch(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=40)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def collect_records():
    soup = fetch(PRODUCT_URL)
    records = {}

    # Основной источник — карточка релизов именно Бухгалтерии 8 для Казахстана, ред. 3.0.
    for row in soup.select("tr"):
        row_text = clean_text(row)
        if not row_text:
            continue
        if "Бухгалтерия 8 для Казахстана" not in row_text:
            continue
        if not re.search(r"\b3\.0\.\d+\.\d+\b", row_text):
            continue

        links = []
        for a in row.select("a[href]"):
            href = urljoin(PRODUCT_URL, a.get("href", ""))
            label = clean_text(a)
            if href.startswith("http"):
                links.append((label, href))

        # Страница "Все дополнения" может содержать перечень отдельных патчей.
        supplement_texts = []
        for label, href in links:
            if "дополн" in label.lower():
                try:
                    detail = fetch(href)
                    detail_text = clean_text(detail)
                    if detail_text:
                        supplement_texts.append(detail_text[:12000])
                except Exception as exc:
                    supplement_texts.append(f"Не удалось прочитать страницу дополнений: {exc}")

        version_match = re.search(r"\b(3\.0\.\d+\.\d+)\b", row_text)
        version = version_match.group(1) if version_match else "unknown"
        key = f"release-{version}"

        payload = {
            "kind": "release_or_supplement",
            "version": version,
            "text": row_text,
            "links": links,
            "supplements": supplement_texts,
        }
        payload["hash"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        records[key] = payload

    if not records:
        raise RuntimeError(
            "Не удалось найти строки Бухгалтерии 8 для Казахстана, ред. 3.0. "
            "Возможно, сайт изменил разметку. Уведомление не отправлено, состояние не перезаписано."
        )
    return records


def make_message(record, changed=False):
    title = "🛠 Изменения / дополнение к релизу" if changed else "🆕 Новый релиз"
    lines = [
        title,
        "1С:Бухгалтерия для Казахстана, редакция 3.0",
        f"Версия: {record['version']}",
        "",
        record["text"][:1000],
    ]
    for detail in record.get("supplements", [])[:2]:
        if detail:
            lines.extend(["", "Информация о дополнениях:", detail[:1300]])
    seen = set()
    for label, href in record.get("links", []):
        if href not in seen:
            seen.add(href)
            lines.append(f"{label or 'Подробнее'}: {href}")
    lines.extend(["", "Источник: " + PRODUCT_URL])
    return "\n".join(lines)


def main():
    current = collect_records()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            previous = json.load(f)
        is_first_run = False
    else:
        previous = {}
        is_first_run = True

    if is_first_run:
        # Не рассылаем архив старых релизов при первом запуске.
        telegram(
            "✅ Мониторинг 1С:Бухгалтерия для Казахстана 3.0 включён.\n"
            f"Найдено записей для отслеживания: {len(current)}.\n"
            "Текущие записи сохранены как начальная база. Новые релизы и изменения "
            "в дополнениях будут приходить отдельными сообщениями."
        )
    else:
        changes = []
        for key, record in current.items():
            old = previous.get(key)
            if old is None:
                changes.append((record, False))
            elif old.get("hash") != record.get("hash"):
                changes.append((record, True))

        for record, changed in changes:
            telegram(make_message(record, changed))

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    print(f"Проверено записей: {len(current)}; первый запуск: {is_first_run}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Ошибка мониторинга: {exc}", file=sys.stderr)
        raise
