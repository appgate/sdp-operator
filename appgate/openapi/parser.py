import datetime
from pathlib import Path
from typing import Optional, Dict, Set, Any, List, Type, FrozenSet, cast, Callable

import yaml
from attr import attrib, make_class
from cryptography.fernet import Fernet

from appgate.attrs import K8S_LOADER
from appgate.bytes import size_attrib_maker, checksum_attrib_maker, certificate_attrib_maker
from appgate.customloaders import CustomFieldsEntityLoader, CustomEntityLoader
from appgate.logger import log
from appgate.openapi.attribmaker import SimpleAttribMaker, create_default_attrib, \
    DeprecatedAttribMaker, UUID_REFERENCE_FIELD, DefaultAttribMaker
from appgate.openapi.types import OpenApiDict, OpenApiParserException, \
    GeneratedEntityFieldDependency, GeneratedEntity, AttributesDict, AttribType, InstanceMakerConfig, \
    AttribMakerConfig, AppgateMetadata, K8S_LOADERS_FIELD_NAME, APPGATE_LOADERS_FIELD_NAME, \
    ENTITY_METADATA_ATTRIB_NAME, APPGATE_METADATA_ATTRIB_NAME
from appgate.openapi.utils import has_default, join, make_explicit_references, is_compound, \
    is_object, is_ref, is_array
from appgate.secrets import PasswordAttribMaker
from appgate.types import BUILTIN_TAGS

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


def set_id_from_metadata(current_id: str, appgate_metadata: AppgateMetadata) -> str:
    return appgate_metadata.uuid or current_id


class IdAttribMaker(SimpleAttribMaker):
    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        values = super().values(attributes, required_fields, instance_maker_config)
        if 'metadata' not in values:
            values['metadata'] = {}
        # sets entity.id from entity.appgate_metadata.id or current id
        values['metadata'][K8S_LOADERS_FIELD_NAME] = [CustomFieldsEntityLoader(
            loader=set_id_from_metadata,
            dependencies=['appgate_metadata'],
            field=self.name,
        )]
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
    def password_attributes(self) -> Dict[str, SimpleAttribMaker]:
        return {k: v for k, v in self.attributes.items() if v.is_password}

    @property
    def dependencies(self) -> Set[GeneratedEntityFieldDependency]:
        dependencies: Set[GeneratedEntityFieldDependency] = set()
        for attrib_name, attrib_attrs in self.attributes.items():
            dependency = attrib_attrs.definition.get(UUID_REFERENCE_FIELD)
            if dependency and isinstance(dependency, list):
                dependencies.add(GeneratedEntityFieldDependency(field_path=attrib_name,
                                                                dependencies=frozenset(dependency)))
            elif dependency:
                dependencies.add(GeneratedEntityFieldDependency(field_path=attrib_name,
                                                                dependencies=frozenset({dependency})))
        return dependencies

    def make_instance(self, instance_maker_config: InstanceMakerConfig) -> GeneratedEntity:
        # Add attributes if needed after instance level
        if 'name' not in self.attributes and instance_maker_config.singleton:
            self.attributes['name'] = create_default_attrib('name', self.name)
        if 'id' not in self.attributes and instance_maker_config.singleton:
            self.attributes['id'] = create_default_attrib('id', self.name)
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
            k8s_loaders = v['metadata'].get(K8S_LOADERS_FIELD_NAME, [])
            custom_k8s_attrib_loaders = []
            for k8s_loader in k8s_loaders:
                if any(map(lambda el: isinstance(k8s_loader, el),
                           {CustomFieldsEntityLoader, CustomEntityLoader})):
                    k8s_custom_entity_loaders.append(k8s_loader)
                else:
                    custom_k8s_attrib_loaders.append(k8s_loader)
            v['metadata'][K8S_LOADERS_FIELD_NAME] = custom_k8s_attrib_loaders
            appgate_loaders = v['metadata'].get(APPGATE_LOADERS_FIELD_NAME, [])
            custom_appgate_attrib_loaders = []
            for appgate_loader in appgate_loaders:
                if any(map(lambda el: isinstance(k8s_loader, el),
                           {CustomFieldsEntityLoader, CustomEntityLoader})):
                    appgate_custom_entity_loaders.append(appgate_loader)
                else:
                    custom_appgate_attrib_loaders.append(appgate_loader)
            v['metadata'][APPGATE_LOADERS_FIELD_NAME] = custom_appgate_attrib_loaders

        # Build the dictionary of attribs
        attrs = {}
        # First attributes with no default values
        for k, v in filter(lambda p: not has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)
        # Now attributes with default values
        for k, v in filter(lambda p: has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)

        # Create attribute to store entity metadata
        entity_metadata_attrib = create_default_attrib(
            ENTITY_METADATA_ATTRIB_NAME,
            {
                'singleton': instance_maker_config.singleton,
                K8S_LOADERS_FIELD_NAME: k8s_custom_entity_loaders or None,
                APPGATE_LOADERS_FIELD_NAME: appgate_custom_entity_loaders or None,
                'passwords': self.password_attributes,
                'dependencies': self.dependencies
            })
        attrs[ENTITY_METADATA_ATTRIB_NAME] = attrib(**entity_metadata_attrib.values(
            self.attributes,
            instance_maker_config.definition.get('required', {}),
            instance_maker_config))

        # Create attribute to store instance metadata
        appgate_metadata_attrib = DefaultAttribMaker(
            tpe=AppgateMetadata,
            base_tpe=AppgateMetadata,
            name=APPGATE_METADATA_ATTRIB_NAME,
            default=None,
            factory=AppgateMetadata,
            definition={},
            repr=True)
        attrs[APPGATE_METADATA_ATTRIB_NAME] = attrib(**appgate_metadata_attrib.values(
            self.attributes,
            instance_maker_config.definition.get('required', {}),
            instance_maker_config))
        cls = make_class(self.name, attrs, slots=True, frozen=True)
        return GeneratedEntity(cls=cls,
                               api_path=instance_maker_config.api_path,
                               singleton=instance_maker_config.singleton)


class ParserContext:
    def __init__(self, spec_entities: Dict[str, str], spec_api_path: Path,
                 secrets_key: Optional[str],
                 k8s_get_secret: Optional[Callable[[str, str], str]]) -> None:
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
        log.trace(f'Registering new class {entity_name}')
        if entity_name in self.entities:
            log.warning(f'Entity %s already registered, ignoring it', entity_name)
        else:
            self.entities[entity_name] = entity
        return self.entities[entity_name]

    def load_namespace(self, namespace: str) -> Dict[str, Any]:
        path = self.spec_api_path / namespace
        if path.name in self.data:
            log.trace('Using cached namespace %s', path)
            return self.data[path.name]
        with path.open('r') as f:
            log.trace('Loading namespace %s from disk', path)
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
            log.trace('Resolving reference %s in current namespace: %s',
                     join('.', new_keys), self.namespace)
            resolved_ref = self.get_keys(new_keys)
        else:
            log.trace('Resolving reference %s in %s namespace', join('.', new_keys), path)
            resolved_ref = Parser(self.parser_context, namespace=path).get_keys(new_keys)
        if not resolved_ref:
            raise OpenApiParserException(f'Unable to resolve reference {reference}')
        return resolved_ref

    def get_keys(self, keys: List[str]) -> Optional[Any]:
        keys_cp = keys.copy()
        data = self.data
        while True:
            try:
                log.trace('Trying %s in [%s]', join('.', keys),
                          join(', ', data.keys()))
                k = keys.pop(0)
            except IndexError:
                log.trace('Keys not found %s', join('.', keys_cp))
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
                log.trace('Key %s not found in [%s]', k, ', '.join(data.keys()))
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
        entity_name = attrib_maker_config.instance_maker_config.entity_name
        attrib_name = attrib_maker_config.name
        tpe = definition.get('type')
        current_level = attrib_maker_config.instance_maker_config.level
        if is_compound(definition):
            definition = self.parse_all_of(definition['allOf'])
            instance_maker_config = InstanceMakerConfig(
                name=attrib_name,
                entity_name=f'{entity_name}_{attrib_name.capitalize()}',
                definition=definition,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=None,
                level=current_level + 1)
            generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
            log.trace('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return SimpleAttribMaker(name=instance_maker_config.name,
                                     tpe=generated_entity.cls,
                                     base_tpe=generated_entity.cls,
                                     default=None,
                                     factory=None,
                                     definition=attrib_maker_config.definition)
        elif not tpe:
            raise Exception('type field not found in %s', definition)
        elif tpe in TYPES_MAP:
            log.trace('Creating new attribute %s.%s :: %s', entity_name, attrib_name,
                      TYPES_MAP[tpe])
            format = definition.get('format', None)
            if format == 'password':
                return PasswordAttribMaker(name=attrib_name,
                                           tpe=TYPES_MAP[tpe],
                                           base_tpe=TYPES_MAP[tpe],
                                           default=DEFAULT_MAP.get(tpe),
                                           factory=None,
                                           definition=attrib_maker_config.definition,
                                           secrets_cipher=self.parser_context.secrets_cipher,
                                           k8s_get_client=self.parser_context.k8s_get_secret)
            elif format == 'date-time':
                return SimpleAttribMaker(name=attrib_name,
                                         tpe=datetime.datetime,
                                         base_tpe=datetime.datetime,
                                         default=None,
                                         factory=None,
                                         definition=attrib_maker_config.definition)
            elif format == 'checksum' and 'x-checksum-source' in attrib_maker_config.definition:
                return checksum_attrib_maker(name=attrib_name,
                                             tpe=TYPES_MAP[tpe],
                                             base_tpe=TYPES_MAP[tpe],
                                             default=DEFAULT_MAP.get(tpe),
                                             factory=None,
                                             definition=attrib_maker_config.definition,
                                             source_field=attrib_maker_config.definition['x-checksum-source'])
            elif format == 'size' and 'x-size-source' in attrib_maker_config.definition:
                return size_attrib_maker(name=attrib_name,
                                         tpe=TYPES_MAP[tpe],
                                         base_tpe=TYPES_MAP[tpe],
                                         default=DEFAULT_MAP.get(tpe),
                                         factory=None,
                                         definition=attrib_maker_config.definition,
                                         source_field=attrib_maker_config.definition['x-size-source'])
            elif attrib_name == 'id':
                return IdAttribMaker(name=attrib_name,
                                     tpe=TYPES_MAP[tpe],
                                     base_tpe=TYPES_MAP[tpe],
                                     default=DEFAULT_MAP.get(tpe),
                                     factory=None,
                                     definition=attrib_maker_config.definition)
            else:
                return SimpleAttribMaker(name=attrib_name,
                                         tpe=TYPES_MAP[tpe],
                                         base_tpe=TYPES_MAP[tpe],
                                         default=DEFAULT_MAP.get(tpe) if format != 'uuid' else None,
                                         factory=None,
                                         definition=attrib_maker_config.definition)
        elif is_array(definition):
            # Recursion here, we parse the items as a type
            log.trace('Creating array type for entity %s and attribute %s', entity_name, attrib_name)
            new_attrib_maker_config = attrib_maker_config.from_key('items')
            if not new_attrib_maker_config:
                raise OpenApiParserException('Unable to get items from array defintion.')
            attr_maker = self.make_type(new_attrib_maker_config)
            log.trace('Creating new attribute %s.%s: FrozenSet[%s]', entity_name, attrib_name,
                      attr_maker.tpe)
            return SimpleAttribMaker(name=attr_maker.name,
                                     tpe=FrozenSet[attr_maker.tpe],  # type: ignore
                                     base_tpe=attr_maker.base_tpe,
                                     default=None,
                                     factory=frozenset,
                                     definition=new_attrib_maker_config.definition)
        elif is_object(definition):
            # Indirect recursion here.
            # Those classes are never registered
            log.trace('Creating object type for entity %s and attribute %s', entity_name, attrib_name)
            current_level = attrib_maker_config.instance_maker_config.level
            instance_maker_config = InstanceMakerConfig(
                name=attrib_name,
                entity_name=f'{entity_name}_{attrib_name.capitalize()}',
                definition=definition,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=None,
                level=current_level + 1)
            generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
            log.trace('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            format = definition.get('format', None)
            if format == 'certificate' and 'x-certificate-source' in attrib_maker_config.definition:
                return certificate_attrib_maker(name=instance_maker_config.name,
                                                tpe=generated_entity.cls,
                                                base_tpe=generated_entity.cls,
                                                default=None,
                                                factory=None,
                                                definition=attrib_maker_config.definition,
                                                source_field=attrib_maker_config.definition['x-certificate-source'],
                                                loader=K8S_LOADER.load)
            else:
                # if nullable is specified then the type should be Optional
                _factory = generated_entity.cls
                if definition.get('nullable'):
                    _factory = None
                return SimpleAttribMaker(name=instance_maker_config.name,
                                         tpe=generated_entity.cls,
                                         base_tpe=generated_entity.cls,
                                         default=None,
                                         factory=_factory,
                                         definition=instance_maker_config.definition)
        raise Exception(f'Unknown type for attribute {entity_name}.{attrib_name}: {definition}')

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
                tpe=attrib.tpe,
                base_tpe=attrib.base_tpe)
        return attrib

    def instance_maker(self, instance_maker_config: InstanceMakerConfig) -> InstanceMaker:
        return InstanceMaker(
            name=instance_maker_config.entity_name,
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
                         singleton: bool) -> Optional[GeneratedEntity]:
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
                                                    entity_name=entity_name,
                                                    definition=definition_to_use,
                                                    singleton=singleton,
                                                    api_path=api_path,
                                                    level=0)
        generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
        return generated_entity
