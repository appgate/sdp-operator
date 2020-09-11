from typing import Callable, Any, List, Dict

from attr import attrs, attrib, evolve

from appgate.openapi.types import AttributesDict, Entity_T

__all__ = [
    'CustomLoader',
    'CustomFieldsEntityLoader',
    'CustomAttribLoader',
    'CustomEntityLoader',
]

from appgate.openapi.utils import get_field


class CustomLoader:
    pass


@attrs()
class CustomAttribLoader(CustomLoader):
    loader: Callable[[Any], Any] = attrib()
    field: str = attrib()

    def load(self, values: AttributesDict) -> AttributesDict:
        v = values.get(self.field)
        if not v:
            return values
        values[self.field] = self.loader(v)
        return values


@attrs()
class CustomFieldsEntityLoader(CustomLoader):
    loader: Callable[..., Any] = attrib()
    field: str = attrib()
    dependencies: List[str] = attrib(factory=list)

    def load(self, orig_values: Dict[str, Any], entity: Any) -> Any:
        deps_set = set(self.dependencies)
        resolved_deps = {(a.name, get_field(entity, a.name))
                         for a in entity.__attrs_attrs__
                         if a.name in self.dependencies}
        resolved_dep_names = {k[0] for k in resolved_deps}
        if resolved_dep_names != set(self.dependencies):
            missing_deps = deps_set.difference(resolved_dep_names)
            raise TypeError(f'Missing dependencies when loading entity: %s',
                            ', '.join(missing_deps))
        field_value = get_field(entity, self.field)
        new_value = self.loader(*([field_value] + list(d[1] for d in resolved_deps)))
        return evolve(entity, **{
            self.field: new_value
        })


@attrs()
class CustomEntityLoader(CustomLoader):
    """
    The most generic CustomLoader
    It gets the entity and then it returns a new entity
    TODO: Check order of executions
    """
    loader: Callable[[Dict[str, Any], Entity_T], Entity_T] = attrib()

    def load(self, orig_values: Dict[str, Any], entity: Any) -> Any:
        return self.loader(orig_values, entity)
