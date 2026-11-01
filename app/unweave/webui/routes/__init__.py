"""Register HTTP API routes on a Router."""

from ..router import Router
from . import meta, projects, system, window


def build_router(library) -> Router:
    router = Router()
    system.register(router, library)
    meta.register(router, library)
    window.register(router, library)
    projects.register(router, library)
    return router
