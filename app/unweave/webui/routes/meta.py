"""MusicBrainz search / cover routes."""


def register(router, library):
    @router.post("/api/metadata/search")
    def search(req, query, **_):
        return {"matches": library.lookup.search(req.json_body())}

    @router.post("/api/metadata/prepare")
    def prepare(req, query, **_):
        return library.lookup.prepare(req.json_body().get("token"))

    @router.get("/api/metadata/cover/{token}")
    def cover(req, query, token, **_):
        item = library.lookup.get(token)
        if not item.get("cover"):
            raise ValueError("Cover not found.")
        req.respond(200, item["cover"], item["cover_type"])
        return None
