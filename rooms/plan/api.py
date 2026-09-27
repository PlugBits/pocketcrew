"""/api/plan のルート。plan.py を薄く呼ぶだけ(core/server.py の同名ハンドラをそのまま移した)。"""
import plan


def get_plan(req):
    return plan.plan()


def post_toggle(req):
    body = req.json()
    return plan.toggle_task(int(body.get("line", -1)))


ROUTES = {
    "GET /": get_plan,
    "POST /toggle": post_toggle,
}
LEGACY = {
    "GET /api/plan": "GET /",
    "POST /api/plan/toggle": "POST /toggle",
}
