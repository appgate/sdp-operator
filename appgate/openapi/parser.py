import hashlib
from pathlib import Path
from typing import Optional, Iterator, Tuple, Dict, Set, Any, List, Type, FrozenSet, cast, Callable

import yaml
from attr import attrib, attrs, make_class
from cryptography.fernet import Fernet
from kubernetes.client import CoreV1Api

from appgate.customloaders import CustomEntityLoader
from appgate.logger import log
from appgate.openapi.attribmaker import SimpleAttribMaker, create_default_attrib, \
    DeprecatedAttribMaker
from appgate.openapi.types import OpenApiDict, OpenApiParserException, \
    EntityDependency, GeneratedEntity, AttributesDict, AttribType, InstanceMakerConfig, AttribMakerConfig
from appgate.openapi.utils import has_default, join, make_explicit_references, is_compound, \
    is_object, is_ref, is_array
from appgate.secrets import PasswordAttribMaker


BUILTIN_TAGS = frozenset({'builtin'})
APPGATE_METADATA_ATTRIB_NAME = '_appgate_metadata'
TYPES_MAP: Dict[str, Type] = {
    'string': str,
    'boolean': bool,
    'integer': int,
    'number': int,
}
DEFAULT_MAP: Dict[str, AttribType] = {
    'string': '',
    'array': frozenset,
}


def checksum_bytes(value: Any, bytes: str) -> str:
    return hashlib.sha256(bytes.encode()).hexdigest()


class ChecksumAttribMaker(SimpleAttribMaker):
    def __init__(self, name: str, tpe: type, default: Optional[AttribType],
                 factory: Optional[type], definition: OpenApiDict,
                 source_field: str) -> None:
        super().__init__(name, tpe, default, factory, definition)
        self.source_field = source_field

    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig',
               ) -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = True
        if 'metadata' not in values:
            values['metadata'] = {}
        values['metadata']['k8s_loader'] = CustomEntityLoader(
            loader=checksum_bytes,
            dependencies=[self.source_field],
            field=self.name,
        )
        return values




class InstanceMaker:
    def __init__(self, name: str, attributes: Dict[str, SimpleAttribMaker]) -> None:
        self.name = name
        self.attributes = attributes

    @property
    def attributes_with_default(self) -> Dict[str, SimpleAttribMaker]:
        return {k: v for k, v in self.attributes.items() if v.has_default}

    @property
    def attributes_without_default(self) -> Dict[str, SimpleAttribMaker]:
        return {k: v for k, v in self.attributes.items() if not v.has_default}

    @property
    def dependencies(self) -> Set[EntityDependency]:
        dependencies: Set[EntityDependency] = set()
        for attrib_name, attrib_attrs in self.attributes.items():
            mt = attrib_attrs.metadata
            if 'x-appgate-entity' in mt:
                dependency = mt['x-appgate-entity']
                dependencies.add(EntityDependency(field=attrib_name,
                                                  dependencies=frozenset(dependency)))

        return dependencies

    def make_instance(self, instance_maker_config: InstanceMakerConfig) -> GeneratedEntity:
        # Add attributes if needed after instance level
        if 'name' not in self.attributes and instance_maker_config.singleton:
            self.attributes['name'] = create_default_attrib(self.name, self.name)
        if 'id' not in self.attributes and instance_maker_config.singleton:
            self.attributes['id'] = create_default_attrib(self.name, self.name)
        if 'tags' not in self.attributes and instance_maker_config.singleton:
            self.attributes['tags'] = create_default_attrib('tags', BUILTIN_TAGS)

        # Get values from attrib makers
        values = dict(
            map(lambda kv: (kv[0], kv[1].values(self.attributes,
                                                instance_maker_config.definition.get('required', {}),
                                                instance_maker_config)),
                filter(lambda kv: not isinstance(kv[1], DeprecatedAttribMaker),
                       self.attributes.items())))
        # Add custom entity loaders if needed
        k8s_custom_entity_loaders = []
        appgate_custom_entity_loaders = []
        for n, v in values.items():
            if 'metadata' not in v:
                continue
            k8s_loader = v['metadata'].get('k8s_loader')
            appgate_loader = v['metadata'].get('appgate_loader')
            if k8s_loader and isinstance(k8s_loader, CustomEntityLoader):
                k8s_custom_entity_loaders.append(k8s_loader)
            if appgate_loader and isinstance(appgate_loader, CustomEntityLoader):
                appgate_custom_entity_loaders.append(k8s_loader)
        metadata_default_attrib = create_default_attrib(
            APPGATE_METADATA_ATTRIB_NAME,
            {
                'singleton': instance_maker_config.singleton,
                'k8s_loader': k8s_custom_entity_loaders or None,
                'appgate_loader': appgate_custom_entity_loaders or None,
            })
        # Build the dictionary of attribs
        attrs = {}
        # First attributes with no default values
        for k, v in filter(lambda p: not has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)
        # Now attributes with default values
        for k, v in filter(lambda p: has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)
        attrs[APPGATE_METADATA_ATTRIB_NAME] = attrib(**metadata_default_attrib.values(
            self.attributes,
            instance_maker_config.definition.get('required', {}),
            instance_maker_config))
        cls = make_class(self.name, attrs, slots=True, frozen=True)
        return GeneratedEntity(cls=cls,
                               entity_dependencies=self.dependencies,
                               api_path=instance_maker_config.api_path)


class ParserContext:
    def __init__(self, spec_entities: Dict[str, str], spec_api_path: Path,
                 secrets_key: Optional[str], k8s_get_secret: Callable[[str, str], str]) -> None:
        self.secrets_cipher = Fernet(secrets_key.encode()) if secrets_key else None
        self.entities: Dict[str, GeneratedEntity] = {}
        self.data: OpenApiDict = {}
        self.spec_api_path: Path = spec_api_path
        self.entity_name_by_path: Dict[str, str] = spec_entities
        self.entity_path_by_name: Dict[str, str] = {v: k for k, v in spec_entities.items()}
        self.k8s_get_secret = k8s_get_secret

    def get_entity_path(self, entity_name: str) -> Optional[str]:
        return self.entity_path_by_name.get(entity_name)

    def get_entity_name(self, entity_path: str) -> Optional[str]:
        return self.entity_name_by_path.get(entity_path)

    def register_entity(self, entity_name: str, entity: GeneratedEntity) -> GeneratedEntity:
        log.info(f'Registering new class {entity_name}')
        if entity_name in self.entities:
            log.warning(f'Entity %s already registered, ignoring it', entity_name)
        else:
            self.entities[entity_name] = entity
        return self.entities[entity_name]

    def load_namespace(self, namespace: str) -> Dict[str, Any]:
        path = self.spec_api_path / namespace
        if path.name in self.data:
            log.debug('Using cached namespace %s', path)
            return self.data[path.name]
        with path.open('r') as f:
            log.info('Loading namespace %s from disk', path)
            self.data[path.name] = yaml.safe_load(f.read())
        return self.data[path.name]


class Parser:
    def __init__(self, parser_context: ParserContext, namespace: str) -> None:
        self.namespace = namespace
        self.parser_context = parser_context
        self.data: Dict[str, Any] = parser_context.load_namespace(namespace)

    def resolve_reference(self, reference: str, keys: List[str]) -> Dict[str, Any]:
        path, ref = reference.split('#', maxsplit=2)
        new_keys = [x for x in ref.split('/') if x] + keys
        if not path:
            # Resolve in current namespace
            # Resolve in current namespace
            log.info('Resolving reference %s in current namespace: %s',
                     join('.', new_keys), self.namespace)
            resolved_ref = self.get_keys(new_keys)
        else:
            log.info('Resolving reference %s in %s namespace', join('.', new_keys), path)
            resolved_ref = Parser(self.parser_context, namespace=path).get_keys(new_keys)
        if not resolved_ref:
            raise OpenApiParserException(f'Unable to resolve reference {reference}')
        return resolved_ref

    def get_keys(self, keys: List[str]) -> Optional[Any]:
        keys_cp = keys.copy()
        data = self.data
        while True:
            try:
                # TODO: This should be TRACE level or something
                # log.debug('Trying %s in [%s]', join('.', keys),
                #          join(', ', data.keys()))
                k = keys.pop(0)
            except IndexError:
                log.debug('Keys not found %s', join('.', keys_cp))
                return None
            # Is the key there?
            if k in data:
                value = data[k]
                # this is a reference, solve it
                if '$ref' in value:
                    data = self.resolve_reference(value['$ref'], keys)
                    # If the resolution succeed that means it should have consumed
                    # all the keys
                    keys = []
                    value = data
                # More keys but we don't have a dict, fail
                elif keys and type(value) is not dict:
                    return None
                else:
                    # iterate
                    data = value

                # No more entries, return the value
                if not keys:
                    return make_explicit_references(value, self.namespace)
            else:
                # key not found
                log.debug('Key %s not found in [%s]', k, ', '.join(data.keys()))
                return None

    def resolve_definition(self, definition: OpenApiDict) -> OpenApiDict:
        if type(definition) is not dict:
            return definition
        for k, v in definition.items():
            if is_ref(v):
                resolved = self.resolve_reference(v['$ref'], [])
                resolved = self.resolve_definition(resolved)
                definition[k] = resolved
            else:
                definition[k] = self.resolve_definition(v)
        return definition

    def parse_all_of(self, definitions: List[OpenApiDict]) -> OpenApiDict:
        for i, d in enumerate(definitions):
            definitions[i] = self.resolve_definition({'to-resolve': d})['to-resolve']
        new_definition: OpenApiDict = {
            'type': 'object',
            'required': [],
            'properties': {},
            'discriminator': {},
            'description': ''
        }
        descriptions = []
        for d in definitions:
            new_definition['required'].extend(d.get('required', {}))
            new_definition['properties'].update(d.get('properties', {}))
            new_definition['discriminator'].update(d.get('discriminator', {}))
            if 'description' in d:
                descriptions.append(d['description'])
        new_definition['description'] = '.'.join(descriptions)
        return new_definition

    def make_type(self, attrib_maker_config: AttribMakerConfig) -> SimpleAttribMaker:
        definition = attrib_maker_config.definition
        entity_name = attrib_maker_config.instance_maker_config.name
        attrib_name = attrib_maker_config.name
        tpe = definition.get('type')
        if is_compound(definition):
            definition = self.parse_all_of(definition['allOf'])
            instance_maker_config = InstanceMakerConfig(
                name=f'{entity_name.capitalize()}_{attrib_name.capitalize()}',
                definition=definition,
                compare_secrets=attrib_maker_config.instance_maker_config.compare_secrets,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=attrib_maker_config.instance_maker_config.api_path,
                level=attrib_maker_config.instance_maker_config.level+1)
            generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return SimpleAttribMaker(name=instance_maker_config.name,
                                     tpe=generated_entity.cls,
                                     default=None,
                                     factory=None,
                                     definition=attrib_maker_config.definition)
        elif not tpe:
            raise Exception('type field not found in %s', definition)
        elif tpe in TYPES_MAP:
            log.debug('Creating new attribute %s.%s :: %s', entity_name, attrib_name,
                      TYPES_MAP[tpe])
            format = definition.get('format', None)
            if format == 'password':
                return PasswordAttribMaker(name=attrib_name,
                                           tpe=TYPES_MAP[tpe],
                                           default=DEFAULT_MAP.get(tpe),
                                           factory=None,
                                           definition=attrib_maker_config.definition,
                                           secrets_cipher=self.parser_context.secrets_cipher,
                                           k8s_get_client=self.parser_context.k8s_get_secret)
            elif isinstance(format, dict) and 'type' in format and format['type'] == 'checksum':
                return ChecksumAttribMaker(name=attrib_name,
                                           tpe=TYPES_MAP[tpe],
                                           default=DEFAULT_MAP.get(tpe),
                                           factory=None,
                                           definition=attrib_maker_config.definition,
                                           source_field=format['source'])
            else:
                return SimpleAttribMaker(name=attrib_name,
                                         tpe=TYPES_MAP[tpe],
                                         default=DEFAULT_MAP.get(tpe),
                                         factory=None,
                                         definition=attrib_maker_config.definition)
        elif is_array(definition):
            # Recursion here, we parse the items as a type
            new_attrib_maker_config = attrib_maker_config.from_key('items')
            if not new_attrib_maker_config:
                raise OpenApiParserException('Unable to get items from array defintion.')
            attr_maker = self.make_type(new_attrib_maker_config)
            log.debug('Creating new attribute %s.%s: FrozenSet[%s]', entity_name, attrib_name,
                      attr_maker.tpe)
            return SimpleAttribMaker(name=attr_maker.name,
                                     tpe=FrozenSet[attr_maker.tpe],  # type: ignore
                                     default=None,
                                     factory=frozenset,
                                     definition=new_attrib_maker_config.definition)
        elif is_object(definition):
            # Indirect recursion here.
            # Those classes are never registered
            instance_maker_config = InstanceMakerConfig(
                name=f'{entity_name.capitalize()}_{attrib_name.capitalize()}',
                definition=definition,
                compare_secrets=attrib_maker_config.instance_maker_config.compare_secrets,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=attrib_maker_config.instance_maker_config.api_path,
                level=attrib_maker_config.instance_maker_config.level + 1)
            generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return SimpleAttribMaker(name=instance_maker_config.name,
                                     tpe=generated_entity.cls,
                                     default=None,
                                     factory=None,
                                     definition=instance_maker_config.definition)
        raise Exception(f'Unknown type for attribute %s.%s: %s', entity_name, attrib_name,
                        definition)

    def attrib_maker(self, attrib_maker_config: AttribMakerConfig) -> SimpleAttribMaker:
        """
        Returns an attribs dictionary used later to call attrs.attrib
        """
        definition = attrib_maker_config.definition
        deprecated = definition.get('deprecated', False)
        attrib = self.make_type(attrib_maker_config)
        if deprecated:
            return DeprecatedAttribMaker(
                name=attrib.name,
                definition=attrib.definition,
                default=attrib.default,
                factory=attrib.factory,
                tpe=attrib.tpe)
        return attrib

    def instance_maker(self, instance_maker_config: InstanceMakerConfig) -> InstanceMaker:
        return InstanceMaker(
            name=instance_maker_config.name,
            attributes={
                nn: self.attrib_maker(instance_maker_config.attrib_maker_config(n))
                for n, nn in instance_maker_config.properties_names
            })

    def register_entity(self, instance_maker_config: InstanceMakerConfig) -> GeneratedEntity:
        instance_maker = self.instance_maker(instance_maker_config)
        generated_entity = instance_maker.make_instance(instance_maker_config)
        self.parser_context.register_entity(entity_name=instance_maker.name,
                                            entity=generated_entity)
        return generated_entity

    def parse_definition(self, keys: List[List[str]], entity_name: str,
                         singleton: bool, compare_secrets: bool) -> Optional[GeneratedEntity]:
        while True:
            errors: List[str] = []
            try:
                k: List[str] = keys.pop()
                definition = self.get_keys(k)
                break
            except OpenApiParserException as e:
                errors.append(str(e))
            except IndexError:
                raise OpenApiParserException(', '.join(errors))

        definition_to_use = None
        if is_compound(definition):
            definition_to_use = self.parse_all_of(cast(dict, definition)['allOf'])
        elif is_object(definition):
            definition_to_use = definition

        if not definition_to_use:
            log.error('Definition %s yet not supported', definition)
            return None
        api_path = self.parser_context.get_entity_path(entity_name)
        instance_maker_config = InstanceMakerConfig(name=entity_name,
                                                    definition=definition_to_use,
                                                    compare_secrets=compare_secrets,
                                                    singleton=singleton,
                                                    api_path=api_path,
                                                    level=0)
        generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
        return generated_entity
