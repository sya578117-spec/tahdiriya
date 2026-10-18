"""مشغّل بوت «تحضيرية» المستقل (polling) — يعمل بدون خادم الويب.

يُشغَّل بهذا الشكل (التوكن عبر البيئة فقط، لا يُكتب في أي ملف):
    BOT_TOKEN=... ADMIN_IDS=... TG_PROXY=http://hatch-egress-proxy:3128 \
        .venv/bin/python bot_runner.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import config
from backend.bot import build_application
from backend.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# كتم سجلات httpx/httpcore: تسجّل عناوين URL الكاملة (وفيها التوكن)
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("tahdiriya.runner")


async def main() -> None:
    if not config.BOT_TOKEN:
        log.error("BOT_TOKEN is not set — exiting")
        raise SystemExit(1)
    db = Database(config.DB_PATH)
    await db.init()
    app = build_application(config.BOT_TOKEN, db)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    me = await app.bot.get_me()
    log.info("BOT POLLING STARTED as @%s", me.username)
    print("BOT POLLING STARTED", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
