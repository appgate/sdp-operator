import pprint
from typing import List, Optional, Dict

from attr import evolve

from appgate.customloaders import CustomEntityLoader
from appgate.logger import log
from appgate.openapi.attribmaker import AttribMaker
from appgate.openapi.types import (
    AttribMakerConfig,
    EntityClassGeneratorConfig,
    AttribType,
    OpenApiDict,
    AttributesDict,
    K8S_LOADERS_FIELD_NAME,
    APPGATE_LOADERS_FIELD_NAME,
    Entity_T,
)


def get_discriminator_maker_config(
    discriminator: dict,
    attrib_maker_config: AttribMakerConfig,
    entity: str,
    attrib_name: str,
) -> List[EntityClassGeneratorConfig]:
    config = []
    for discriminator_entity, definition in discriminator["mapping"].items():
        log.info(
            "Creating object type for entity %s and attribute %s",
            f"{entity}_{discriminator_entity}",
            attrib_name,
        )

        current_level = attrib_maker_config.instance_maker_config.level
        discriminator_maker_config = EntityClassGeneratorConfig(
            name=discriminator_entity,
            entity_name=f"{entity}_{discriminator_entity}",
            definition=definition,
            singleton=attrib_maker_config.instance_maker_config.singleton,
            api_path=None,
            level=current_level,
        )
        config.append(discriminator_maker_config)
    return config


class DiscriminatorAttribMaker(AttribMaker):
    def __init__(
        self,
        name: str,
        tpe: type,
        base_tpe: type,
        default: Optional[AttribType],
        factory: Optional[type],
        top_level_definition: OpenApiDict,
        discriminator_property_name: str,
        entity_map: dict,
        definition_map: dict,
        config_map: dict,
        repr: bool = True,
    ) -> None:
        super().__init__(
            name, tpe, base_tpe, default, factory, top_level_definition, repr
        )
        self.discriminator_property_name = discriminator_property_name
        self.entity_map = entity_map
        self.definition_map = definition_map
        self.config_map = config_map

    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: EntityClassGeneratorConfig,
    ) -> AttributesDict:
        def validate_fields(original, entity: Entity_T) -> Entity_T:
            type = original["type"]

            # Check if there are missing fields required for this type. Exclude readOnly attributes.
            required_fields = set(
                k for k in self.definition_map[type]["required"] if k != "id"
            )
            missing_fields = required_fields.difference(set(original.keys()))
            if len(missing_fields) > 0:
                raise TypeError(
                    f"Missing required fields when loading entity: {', '.join(missing_fields)}"
                )

            return entity

        values = super().values(attributes, required_fields, instance_maker_config)
        values["eq"] = False

        if "metadata" not in values:
            values["metadata"] = {}

        values["metadata"][APPGATE_LOADERS_FIELD_NAME] = [
            CustomEntityLoader(loader=validate_fields)
        ]

        values["metadata"][K8S_LOADERS_FIELD_NAME] = [
            CustomEntityLoader(loader=validate_fields)
        ]

        return values
