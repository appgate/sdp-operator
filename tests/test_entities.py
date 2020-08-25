import os
from pathlib import Path

import pytest
import yaml
from typedload import load

from appgate.attrs import APPGATE_LOADER, K8S_LOADER, K8S_DUMPER, APPGATE_DUMPER, APPGATE_DUMPER_WITH_SECRETS
from appgate.logger import set_level
from appgate.openapi import parse_files
from appgate.types import generate_api_spec

api_spec = generate_api_spec()
entities = api_spec.entities


EntityTest1 = None
TestOpenAPI = None


def load_test_open_api_spec():
    global TestOpenAPI
    set_level(log_level='debug')
    spec = {
        '/entity-test1': 'EntityTest1',
        '/entity-test2': 'EntityTest2',
    }
    if not TestOpenAPI:
        open_api_spec = parse_files(spec_entities=spec,
                                    spec_directory=Path('tests/resources/'),
                                    spec_file='test_entity.yaml')
        TestOpenAPI = open_api_spec.entities
    return TestOpenAPI


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
    EntityTest1 = load_test_open_api_spec()['EntityTest1'].cls
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
    EntityTest1 = load_test_open_api_spec()['EntityTest1'].cls
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
    EntityTest1 = load_test_open_api_spec()['EntityTest1'].cls
    with pytest.raises(TypeError,
                       match=f".*unexpected keyword argument 'fieldThree'"):
        EntityTest1(fieldOne='this is read only', fieldTwo='this is write only',
                    fieldThree='this is deprecated', fieldFour='this is a field')


def test_write_only_attribute_load():
    EntityTest2 = load_test_open_api_spec()['EntityTest2'].cls
    e_data = {
        'fieldOne': '1234567890',
        'fieldTwo': 'this is writet only',
        'fieldThree': 'this is a field',
    }
    e = APPGATE_LOADER.load(e_data, EntityTest2)
    assert e == EntityTest2(fieldOne=None,
                            fieldTwo='this is write only',
                            fieldThree='this is a field')
    e = K8S_LOADER.load(e_data, EntityTest2)
    assert e == EntityTest2(fieldOne='1234567890',
                            fieldTwo=None,
                            fieldThree='this is a field')


def test_write_only_password_attribute_dump():
    EntityTest2 = load_test_open_api_spec()['EntityTest2'].cls
    e = EntityTest2(fieldOne='1234567890',
                    fieldTwo='this is write only',
                    fieldThree='this is a field')
    e_data = {
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
    }
    assert APPGATE_DUMPER.dump(e) == e_data
    e_data = {
        'fieldOne': '1234567890',
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
    }
    assert K8S_DUMPER.dump(e) == e_data
    e_data = {
        'fieldOne': '1234567890',
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
    }
    assert APPGATE_DUMPER_WITH_SECRETS.dump(e) == e_data
