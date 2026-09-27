"""/api/daily, /api/brief: 日次まとめ・朝の便り。実体は core/collect.py + daily_brief.py。"""
from core import collect, util
from daily_brief import morning_brief


def _post_daily(req):
    res = collect.daily_summary(force=True)
    util.invalidate_status()
    return res


def _post_brief(req):
    res = morning_brief(force=True)
    util.invalidate_status()
    return res


ROUTES = {
    "GET /": lambda req: collect.daily_text(),
    "POST /": _post_daily,
    "GET /brief": lambda req: collect.brief_text(),
    "POST /brief": _post_brief,
}

LEGACY = {
    "GET /api/daily": "GET /",
    "POST /api/daily": "POST /",
    "GET /api/brief": "GET /brief",
    "POST /api/brief": "POST /brief",
}
