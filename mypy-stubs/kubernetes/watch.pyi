from typing import Any, Dict, Iterator


class Watch:
    def stream(self, *args, **kwargs) -> Iterator[Dict[str, Any]]: ...
