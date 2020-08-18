import os
from pathlib import Path

import yaml
from typedload import load

from appgate.types import generated_entities


entities = generated_entities().entities


def test_load_entities_v12():
    """
    Read all yaml files in v12 and try to load them according to the kind.
    """
    for f in os.listdir('tests/resources/v12'):
        with (Path('tests/resources/v12') / f).open('r') as f:
            documents = list(yaml.safe_load_all(f))
            for d in documents:
                e = entities[d['kind']].cls
                assert isinstance(load(d['spec'], e), e)
