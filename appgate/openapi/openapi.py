from pathlib import Path
from typing import Dict, Optional, Tuple, Type, Callable

import yaml

from appgate.client import AppgateClient, EntityClient
from appgate.logger import log
from appgate.openapi.parser import is_compound, Parser, ParserContext
from appgate.openapi.types import APISpec, OpenApiParserException, SPEC_ENTITIES, K8S_APPGATE_DOMAIN, \
    K8S_APPGATE_VERSION

__all__ = [
    'parse_files',
    'SPEC_DIR',
    'generate_crd',
    'entity_names',
    'generate_api_spec',
    'generate_api_spec_clients',
]


SPEC_DIR = 'api_specs/v12'
K8S_API_VERSION = 'apiextensions.k8s.io/v1beta1'
K8S_CRD_KIND = 'CustomResourceDefinition'
LIST_PROPERTIES = {'range', 'data', 'query', 'orderBy', 'descending', 'filterBy'}


def parse_files(spec_entities: Dict[str, str],
                spec_directory: Optional[Path] = None,
                spec_file: str = 'api_specs.yml',
                k8s_get_secret: Optional[Callable[[str, str], str]] = None,
                secrets_key: Optional[str] = None) -> APISpec:
    parser_context = ParserContext(spec_entities=spec_entities,
                                   spec_api_path=spec_directory \
                                                 or Path(SPEC_DIR),
                                   secrets_key=secrets_key,
                                   k8s_get_secret=k8s_get_secret)
    parser = Parser(parser_context, spec_file)
    # First parse those paths we are interested in
    for path, v in parser.data['paths'].items():
        if not parser_context.get_entity_name(path):
            continue
        entity_name = spec_entities[path]
        log.info('Generating entity %s for path %s', entity_name, path)
        keys = ['requestBody', 'content', 'application/json', 'schema']
        # Check if path returns a singleton or a list of entities
        get_schema = parser.get_keys(keys=['paths', path, 'get', 'responses', '200',
                                           'content', 'application/json', 'schema'])
        if isinstance(get_schema, dict) and is_compound(get_schema):
            # TODO: when data.items is a compound method the references are not resolved.
            parsed_schema = parser.parse_all_of(get_schema['allOf'])
        elif isinstance(get_schema, dict):
            parsed_schema = get_schema
        else:
            parsed_schema = {}
        singleton = not all(map(lambda f: f in parsed_schema.get('properties', {}),
                                LIST_PROPERTIES))
        parser.parse_definition(entity_name=entity_name,
                                keys=[
                                     ['paths', path] + ['post'] + keys,
                                     ['paths', path] + ['put'] + keys
                                 ],
                                singleton=singleton)

    # Now parse the API version
    api_version_str = parser.get_keys(['info', 'version'])
    if not api_version_str:
        raise OpenApiParserException('Unable to find Appgate API version')
    try:
        api_version = api_version_str.split(' ')[2]
    except IndexError:
        raise OpenApiParserException('Unable to find Appgate API version')
    return APISpec(entities=parser_context.entities,
                   api_version=api_version)


def entity_names(entity: type, short_names: Dict[str, str]) -> Tuple[str, str, str, str]:
    name = entity.__name__
    short_name = name[0:3].lower()
    if short_name in short_names:
        conflicting_name_prefix = short_names[short_name][0:2]
        # Another CRD has the same short name, iterate letters until one is free
        for i in range(len(name) - 3):
            short_name = f'{conflicting_name_prefix}{name[i]}'.lower()
            if short_name not in short_names:
                continue
        if short_name in short_names:
            raise OpenApiParserException('Unable to generate short name for entity %s', name)
    short_names[short_name] = name
    singular_name = name.lower()
    if singular_name.endswith('y'):
        plural_name = f'{singular_name[:-1]}ies'
    else:
        plural_name = f'{singular_name}s'
    return name, singular_name, plural_name, short_name


def generate_crd(entity: Type, short_names: Dict[str, str]) -> str:
    name, singular_name, plural_name, short_name = entity_names(entity, short_names)
    crd = {
        'apiVersion': K8S_API_VERSION,
        'kind': K8S_CRD_KIND,
        'metadata': {
            'name': f'{plural_name}.{K8S_APPGATE_DOMAIN}',
        },
        'spec': {
            'group': K8S_APPGATE_DOMAIN,
            'versions': [{
                'name': K8S_APPGATE_VERSION,
                'served': True,
                'storage': True
            }],
            'scope': 'Namespaced',
            'names': {
                'singular': singular_name,
                'plural': plural_name,
                'kind': name,
                'shortNames': [
                    short_name
                ]
            }
        }
    }
    """
    TODO: Iterate over all attributes here to generate the spec
    for a in entity.__attrs_attrs__:
        spec = a.metadata['spec']
        str[a.name] = spec()
    """
    return yaml.safe_dump(crd)


def generate_api_spec(spec_directory: Optional[Path] = None,
                      secrets_key: Optional[str] = None,
                      k8s_get_secret: Optional[Callable[[str, str], str]] = None) -> APISpec:
    """
    Parses openapi yaml files and generates the ApiSpec.
    """
    return parse_files(SPEC_ENTITIES, spec_directory=spec_directory,
                       secrets_key=secrets_key,
                       k8s_get_secret=k8s_get_secret)



MAGIC_ENTITIES = {
    'Site': [
        # Use '6f6fa9d9-17b2-4157-9f68-e97662acccdf' to collect logs
        # from all the appliances
        '6f6fa9d9-17b2-4157-9f68-e97662acccdf',
        # Use '6263435b-c9f6-4b7f-99f8-37e2e6b006a9' to collect logs
        # from appliances without a site.
        '6263435b-c9f6-4b7f-99f8-37e2e6b006a9'
    ]
}


def generate_api_spec_clients(api_spec: APISpec,
                              appgate_client: AppgateClient) -> Dict[str, EntityClient]:
    def _entity_client(e_name: str, e: GeneratedEntity) -> EntityClient:
        magic_entities = None
        if e_name in MAGIC_ENTITIES:
            magic_entities = [e.cls(name=magic_instance, id=magic_instance,
                                    tags=frozenset('builtin'))
             for magic_instance in MAGIC_ENTITIES[e_name]]
        return appgate_client.entity_client(e.cls, e.api_path, singleton=e.singleton,
                                            magic_entities=magic_entities)

    return {
        n: _entity_client(n, e)
        for n, e in api_spec.entities.items()
        if e.api_path
    }
