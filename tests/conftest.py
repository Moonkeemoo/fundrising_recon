"""Герметичність тестів: НЕ читаємо реальний .env і не залежимо від ключів у
оточенні розробника. Інакше наявність ключів у .env ламає graceful-skip тести.

Виконується до імпорту fundrec.config у тест-модулях (pytest вантажить conftest
першим), тож автозавантаження .env вимкнеться, а ключі не «протечуть» у тести.
"""
from __future__ import annotations

import os

os.environ["FUNDREC_SKIP_DOTENV"] = "1"
for _k in (
    "YOUTUBE_API_KEY", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
    "META_ADS_TOKEN", "FUNDREC_CRITIC_API_KEY",
):
    os.environ.pop(_k, None)
