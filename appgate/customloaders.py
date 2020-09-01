from typing import Callable, Any, List

from attr import attrs, attrib, evolve

from appgate.openapi import AttributesDict, get_field


__all__ = [
    'CustomLoader',
    'CustomEntityLoader',
    'CustomAttribLoader',
]


class CustomLoader:
    pass


@attrs()
class CustomAttribLoader(CustomLoader):
    loader: Callable[[Any], Any] = attrib()
    field: str = attrib()

    def load(self, values: AttributesDict) -> AttributesDict:
        v = values[self.field]
        values[self.field] = self.loader(v)
        return values


@attrs()
class CustomEntityLoader(CustomLoader):
    loader: Callable[..., Any] = attrib()
    field: str = attrib()
    dependencies: List[str] = attrib(factory=list)

    def load(self, entity: Any) -> Any:
        deps = [get_field(entity, a.name) for a in entity.__attrs_attrs__
                if a.name in self.dependencies]
        if len(deps) != len(self.dependencies):
            # TODO: Return the attributes missing
            raise TypeError('Missing dependencies when loading entity')
        field_value = get_field(entity, self.field)
        new_value = self.loader(*([field_value] + deps))
        return evolve(entity, **{
            self.field: new_value
        })