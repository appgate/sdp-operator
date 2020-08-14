import os
from pathlib import Path

import yaml
from typedload import load

from appgate.types import generate_entities


entities = generate_entities()


def test_load_entities_v12():
    """
    Read all yaml files in v12 and try to load them according to the kind.
    """
    for f in os.listdir('tests/resources/v12'):
        with (Path('tests/resources/v12') / f).open('r') as f:
            documents = list(yaml.safe_load_all(f))
            for d in documents:
                e = entities[d['kind']][0]
                assert isinstance(load(d['spec'], e), e)
