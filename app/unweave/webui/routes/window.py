"""Desktop window chrome actions (pywebview bridge)."""


def register(router, library):
    @router.get("/api/window/bounds")
    def bounds(req, query, **_):
        return library.window_action("bounds")

    @router.post("/api/window/{action}")
    def action(req, query, action, **_):
        return library.window_action(action, req.json_body())
