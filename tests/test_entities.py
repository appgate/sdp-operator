import os
from pathlib import Path

import pytest
import yaml
from typedload import load

from appgate.attrs import APPGATE_LOADER, K8S_LOADER, K8S_DUMPER, APPGATE_DUMPER
from appgate.logger import set_level
from appgate.openapi import parse_files
from appgate.types import generate_api_spec

api_spec = generate_api_spec()
entities = api_spec.entities


EntityTest1 = None


def load_entity_test1():
    global EntityTest1
    set_level(log_level='debug')
    spec = {
        '/entity-test1': 'EntityTest1'
    }
    if not EntityTest1:
        open_api_spec = parse_files(spec_entities=spec,
                                    spec_directory=Path('tests/resources/'),
                                    spec_file='test_entity.yaml')
        EntityTest1 = open_api_spec.entities['EntityTest1'].cls
    return EntityTest1


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


def test_loader_1():
    EntityTest1 = load_entity_test1()
    entity_1 = {
        'fieldOne': 'this is read only',
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is deprecated',
        'fieldFour': 'this is a field',
    }
    e = APPGATE_LOADER.load(entity_1, EntityTest1)
    assert e == EntityTest1(fieldOne='this is read only', fieldTwo=None,
                            fieldFour='this is a field')
    e = K8S_LOADER.load(entity_1, EntityTest1)
    assert e == EntityTest1(fieldOne=None, fieldTwo='this is write only',
                            fieldFour='this is a field')


def test_dumper_1():
    EntityTest1 = load_entity_test1()
    e1 = EntityTest1(fieldOne='this is read only', fieldTwo='this is write only',
                     fieldFour='this is a field')
    e1_data = {
        'fieldTwo': 'this is write only',
        'fieldFour': 'this is a field',
    }
    e = APPGATE_DUMPER.dump(e1)
    assert e == e1_data
    e1_data = {
        'fieldTwo': 'this is write only',
        'fieldFour': 'this is a field',
    }
    e = K8S_DUMPER.dump(e1)
    assert e == e1_data


def test_deprecated_entity():
    EntityTest1 = load_entity_test1()
    with pytest.raises(TypeError,
                       match=f".*unexpected keyword argument 'fieldThree'"):
        EntityTest1(fieldOne='this is read only', fieldTwo='this is write only',
                    fieldThree='this is deprecated', fieldFour='this is a field')
