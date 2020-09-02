from typing import Callable, Any, List

from attr import attrs, attrib, evolve

from appgate.openapi.types import AttributesDict

__all__ = [
    'CustomLoader',
    'CustomEntityLoader',
    'CustomAttribLoader',
]

from appgate.openapi.utils import get_field


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
