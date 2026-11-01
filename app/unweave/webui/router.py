"""Tiny method+path router for the stdlib HTTP handler (Express-style register)."""


class Router:
    """Match GET/POST paths with optional `{param}` segments."""

    def __init__(self):
        self._routes = []  # (method, parts, handler)

    def add(self, method: str, path: str, handler):
        parts = []
        for segment in path.strip("/").split("/"):
            if len(segment) >= 2 and segment[0] == "{" and segment[-1] == "}":
                parts.append(("param", segment[1:-1]))
            else:
                parts.append(("lit", segment))
        self._routes.append((method.upper(), tuple(parts), handler))
        return handler

    def get(self, path: str, handler=None):
        if handler is not None:
            return self.add("GET", path, handler)

        def decorator(fn):
            return self.add("GET", path, fn)

        return decorator

    def post(self, path: str, handler=None):
        if handler is not None:
            return self.add("POST", path, handler)

        def decorator(fn):
            return self.add("POST", path, fn)

        return decorator

    def match(self, method: str, path: str):
        segments = path.strip("/").split("/") if path.strip("/") else []
        method = method.upper()
        for route_method, parts, handler in self._routes:
            if route_method != method or len(parts) != len(segments):
                continue
            params = {}
            matched = True
            for (kind, name), segment in zip(parts, segments):
                if kind == "lit":
                    if name != segment:
                        matched = False
                        break
                else:
                    params[name] = segment
            if matched:
                return handler, params
        return None, None

    def handle(self, method: str, path: str, query: dict, request):
        handler, params = self.match(method, path)
        if handler is None:
            raise ValueError("Unknown API route.")
        return handler(request, query=query, **params)
