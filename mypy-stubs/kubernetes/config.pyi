from typing import Tuple, List, Any


class ConfigException(Exception):
    pass


def load_kube_config() -> None: ...

def list_kube_config_contexts() -> Tuple[List[Any], Any]: ...

def load_incluster_config() -> None: ...
