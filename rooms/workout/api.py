"""/api/workout: log.md の解析 + Strong CSV の取り込み。実体は workout.py。"""
import workout

ROUTES = {
    "GET /": lambda req: workout.parse_log(),
    "POST /import": lambda req: workout.import_inbox(),
}

LEGACY = {
    "GET /api/workout": "GET /",
    "POST /api/workout/import": "POST /import",
}
