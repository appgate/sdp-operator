from pathlib import Path

from appgate.openapi.openapi import generate_crd, generate_api_spec, SPEC_DIR


def test_generate_crd():
    for version in ["v12", "v13", "v14", "v15", "v16"]:
        open_api = generate_api_spec(Path(SPEC_DIR).parent / version)
        for k, v in open_api.entities.items():
            crd = generate_crd(open_api.entities[k].cls, {})
            assert crd
