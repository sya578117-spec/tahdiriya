"""التحقق من بيانات Telegram WebApp (initData) — حسب توثيق تيليجرام الرسمي.

الخوارزمية:
  data_check_string = ترتيب أبجدي لأزواج key=<value> (بدون hash) مفصولة بسطر جديد
  secret_key = HMAC_SHA256(key=b"WebAppData", msg=BOT_TOKEN)
  hash = HMAC_SHA256(key=secret_key, msg=data_check_string)  (hex)
  يُقارن مع حقل hash المستلم بمقارنة ثابتة الزمن.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# صلاحية بيانات التفويض: 24 ساعة
MAX_AUTH_AGE_SECONDS = 24 * 3600


class InitDataError(ValueError):
    """يُرفع عند فشل التحقق من initData."""


def validate_init_data(init_data: str, bot_token: str) -> dict:
    """يتحقق من initData ويعيد قاموس المستخدم (حقل user) عند النجاح.

    يرفع InitDataError عند أي فشل — لا يُعاد أي جزء من التوكن في الرسائل.
    """
    if not init_data or not bot_token:
        raise InitDataError("missing data")

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception as exc:  # noqa: BLE001
        raise InitDataError("malformed data") from exc

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("bad signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("bad auth_date") from exc
    if abs(time.time() - auth_date) > MAX_AUTH_AGE_SECONDS:
        raise InitDataError("expired")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise InitDataError("bad user payload") from exc
    if not isinstance(user, dict) or "id" not in user:
        raise InitDataError("bad user payload")
    return user
