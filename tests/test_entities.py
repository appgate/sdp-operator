import datetime
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from appgate.attrs import (
    APPGATE_LOADER,
    K8S_LOADER,
    K8S_DUMPER,
    APPGATE_DUMPER,
    DIFF_DUMPER,
)
from appgate.openapi.openapi import generate_api_spec, SPEC_DIR
from appgate.openapi.types import AppgateMetadata, AppgateTypedloadException
from tests.utils import (
    load_test_open_api_spec,
    CERTIFICATE_FIELD,
    PUBKEY_FIELD,
    SUBJECT,
    ISSUER,
    PEM_TEST,
    join_string,
    FINGERPRINT,
)


def test_load_entities_v12():
    """
    Read all yaml files in v12 and try to load them according to the kind.
    """
    open_api = generate_api_spec(Path(SPEC_DIR).parent / "v12")
    entities = open_api.entities
    for f in os.listdir("tests/resources/v12"):
        with (Path("tests/resources/v12") / f).open("r") as f:
            documents = list(yaml.safe_load_all(f))
            for d in documents:
                e = entities[d["kind"]].cls
                assert isinstance(APPGATE_LOADER.load(d["spec"], None, e), e)


def test_load_entities_v16():
    """
    Real all yaml files in v16 and try to load them according to the kind
    """
    open_api = generate_api_spec(Path("api_specs/v16").parent / "v16")
    entities = open_api.entities
    for f in os.listdir("tests/resources/v16"):
        with (Path("tests/resources/v16") / f).open("r") as f:
            documents = list(yaml.safe_load_all(f))
            for d in documents:
                e = entities[d["kind"]].cls
                assert isinstance(APPGATE_LOADER.load(d["spec"], None, e), e)


def test_loader_deprecated_required():
    entities = load_test_open_api_spec(secrets_key=None, reload=True).entities

    # entity with field fieldThree required and deprecated at the same time
    # required wins, so we need to pass it
    EntityTest0 = entities["EntityTest0"].cls
    with pytest.raises(TypeError) as ex:
        e0 = EntityTest0()
    assert (
        str(ex.value)
        == "EntityTest0.__init__() missing 1 required positional argument: 'fieldThree'"
    )

    # entity with field fieldThree deprecated but not required
    # we don't need to pass it
    EntityTest1 = entities["EntityTest1"].cls
    e1 = EntityTest1()
    assert e1


def test_loader_discriminator():
    entities = load_test_open_api_spec(secrets_key=None, reload=True).entities

    EntityDiscriminator = entities["EntityDiscriminator"].cls
    EntityDiscriminatorOne = entities["EntityDiscriminator_DiscriminatorOne"].cls
    EntityDiscriminatorTwo = entities["EntityDiscriminator_DiscriminatorTwo"].cls

    e1 = EntityDiscriminator(
        type="DiscriminatorOne", fieldOne="foo", discriminatorOneFieldOne="foo"
    )
    assert e1
    e2 = EntityDiscriminator(
        type="DiscriminatorTwo", fieldOne="foo", discriminatorTwoFieldTwo=False
    )
    assert e2
    e3 = EntityDiscriminatorOne(fieldOne="foo", discriminatorOneFieldOne="foo")
    assert e3
    e4 = EntityDiscriminatorTwo(fieldOne="foo", discriminatorTwoFieldTwo=False)
    assert e4

    # EntityDiscriminator with type DiscriminatorOne
    data1 = {
        "id": "foo",
        "name": "bar",
        "fieldOne": "hello",
        "type": "DiscriminatorOne",
        "discriminatorOneFieldOne": "hi",
        "discriminatorOneFieldTwo": "bye",
    }
    e1 = APPGATE_LOADER.load(data1, None, EntityDiscriminator)
    assert e1 == EntityDiscriminator(
        type="DiscriminatorOne",
        fieldOne="hello",
        discriminatorOneFieldOne="hi",
        discriminatorOneFieldTwo="bye",
    )

    # EntityDiscriminator with type DiscriminatorTwo
    data2 = {
        "id": "foo",
        "name": "bar",
        "fieldOne": "foobar",
        "type": "DiscriminatorTwo",
        "discriminatorTwoFieldOne": True,
        "discriminatorTwoFieldTwo": False,
    }
    e2 = APPGATE_LOADER.load(data2, None, EntityDiscriminator)
    assert e2 == EntityDiscriminator(
        type="DiscriminatorTwo",
        fieldOne="foobar",
        discriminatorTwoFieldOne=True,
        discriminatorTwoFieldTwo=False,
    )

    # EntityDiscriminator with type DiscriminatorOne missing required field
    data3 = {
        "id": "foo",
        "name": "bar",
        "fieldOne": "hi",
        "type": "DiscriminatorOne",
        "discriminatorOneFieldTwo": False,
    }
    with pytest.raises(AppgateTypedloadException) as ex:
        APPGATE_LOADER.load(data3, None, EntityDiscriminator)
    assert (
        str(ex.value)
        == "Missing required fields when loading entity: discriminatorOneFieldOne\nPath: ."
    )


def test_loader_0():
    entities = load_test_open_api_spec(secrets_key=None, reload=True).entities
    EntityDep5 = entities["EntityDep5"].cls
    EntityDep5_Obj1 = entities["EntityDep5_Obj1"].cls
    EntityDep5_Obj1_Obj2 = entities["EntityDep5_Obj1_Obj2"].cls
    data = {"id": "id5", "name": "dep51", "obj1": {"obj2": {"dep1": "dep11"}}}
    e = APPGATE_LOADER.load(data, None, EntityDep5)
    assert e == EntityDep5(
        id="id5",
        name="dep51",
        obj1=EntityDep5_Obj1(obj2=EntityDep5_Obj1_Obj2(dep1="dep11")),
    )


def test_loader_1():
    EntityTest1 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest1"]
        .cls
    )
    entity_1 = {
        "fieldOne": "this is read only",
        "fieldTwo": "this is write only",
        "fieldThree": "this is deprecated",
        "fieldFour": "this is a field",
        "from": "this has a weird key name",
    }
    e = APPGATE_LOADER.load(entity_1, None, EntityTest1)
    assert e == EntityTest1(
        fieldOne="this is read only",
        fieldTwo=None,
        fieldFour="this is a field",
        fromm="this has a weird key name",
    )
    assert e != EntityTest1(
        fieldOne=None,
        fieldTwo="this is write only",
        fieldFour="this is a field that changed",
    )
    assert e.fieldOne == "this is read only"
    assert e.fieldTwo is None

    e = K8S_LOADER.load(entity_1, None, EntityTest1)
    assert e == EntityTest1(
        fieldOne=None,
        fieldTwo="this is write only",
        fieldFour="this is a field",
        fromm="this has a weird key name",
    )
    assert e != EntityTest1(
        fieldOne=None,
        fieldTwo="this is write only",
        fieldFour="this is a field that changed",
        fromm="this has a weird key name",
    )


def test_loader_2():
    """
    Test that id fields are created if missing
    """
    EntityTestWithId = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestWithId"]
        .cls
    )
    appgate_metadata = {"uuid": "666-666-666-666-666-777"}
    entity_1 = {
        "fieldOne": "this is read only",
        "fieldTwo": "this is write only",
        "fieldThree": "this is deprecated",
        "fieldFour": "this is a field",
    }

    with patch("appgate.openapi.attribmaker.uuid4") as uuid4:
        uuid4.return_value = "111-111-111-111-111"
        e = K8S_LOADER.load(entity_1, None, EntityTestWithId)
        # Normally we create a new uuid value for id if it's not present
        assert e.id == "111-111-111-111-111"
        entity_2 = entity_1
        entity_2["appgate_metadata"] = appgate_metadata
        # If we have in metadata we use it
        e = K8S_LOADER.load(entity_2, None, EntityTestWithId)
        assert e.id == "666-666-666-666-666-777"


def test_loader_3():
    """
    Test load metadata
    """
    EntityTest1 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest1"]
        .cls
    )
    appgate_metadata = {"uuid": "666-666-666-666-666-666"}
    entity_1 = {
        "fieldOne": "this is read only",
        "fieldTwo": "this is write only",
        "fieldThree": "this is deprecated",
        "fieldFour": "this is a field",
        "appgate_metadata": appgate_metadata,
    }

    e = K8S_LOADER.load(entity_1, None, EntityTest1)
    # We load instance metadata
    assert e.appgate_metadata == AppgateMetadata(uuid="666-666-666-666-666-666")
    assert e == EntityTest1(
        fieldOne=None,
        fieldTwo="this is write only",
        fieldFour="this is a field",
        appgate_metadata=AppgateMetadata(uuid="666-666-666-666-666-666"),
    )
    # isntance metadata is not compared
    assert e == EntityTest1(
        fieldOne=None,
        fieldTwo="this is write only",
        fieldFour="this is a field",
        appgate_metadata=AppgateMetadata(uuid="333-333-333-333-333"),
    )


def test_loader_4():
    """
    Test load nested fields with sane default values.
    These fields are not Optional, they just implement a default factory method
    """
    api_spec = load_test_open_api_spec(secrets_key=None, reload=True)
    EntityDepNested7 = api_spec.entities["EntityDepNested7"].cls
    EntityDepNested7_Deps = api_spec.entities["EntityDepNested7_Deps"].cls
    EntityDepNested7_Actions = api_spec.entities["EntityDepNested7_Actions"].cls
    EntityDepNested7_Actions_Monitor = api_spec.entities[
        "EntityDepNested7_Actions_Monitor"
    ].cls

    entity_7 = {
        "name": "n1",
        "deps": {"field1": "f1", "field2": "f2"},
        "actions": [
            {
                "subtype": "tcp_up",
                "action": "allow",
                "hosts": ["h1", "h2"],
                "ports": ["666"],
            }
        ],
    }

    e = K8S_LOADER.load(entity_7, None, EntityDepNested7)
    assert e == EntityDepNested7(
        name="n1",
        deps=EntityDepNested7_Deps(field1="f1", field2="f2"),
        actions=frozenset(
            {
                EntityDepNested7_Actions(
                    subtype="tcp_up",
                    action="allow",
                    hosts=frozenset({"h1", "h2"}),
                    ports=frozenset({"666"}),
                    monitor=EntityDepNested7_Actions_Monitor(),
                )
            }
        ),
    )


def test_loader_5():
    """
    Test load nested fields with sane default values.
    These fields are not Optional, they just implement a default factory method
    """
    api_spec = load_test_open_api_spec(secrets_key=None, reload=True)
    EntityDepNestedNullable = api_spec.entities["EntityDepNestedNullable"].cls
    EntityDepNestedNullable_Actions = api_spec.entities[
        "EntityDepNestedNullable_Actions"
    ].cls

    entity_nullable = {
        "name": "n1",
        "deps": {"field1": "f1", "field2": "f2"},
        "actions": [
            {
                "subtype": "tcp_up",
                "action": "allow",
                "hosts": ["h1", "h2"],
                "ports": ["666"],
            }
        ],
    }

    e = K8S_LOADER.load(entity_nullable, None, EntityDepNestedNullable)
    assert e == EntityDepNestedNullable(
        name="n1",
        actions=frozenset(
            {
                EntityDepNestedNullable_Actions(
                    subtype="tcp_up",
                    action="allow",
                    hosts=frozenset({"h1", "h2"}),
                    ports=frozenset({"666"}),
                    monitor_nullable=None,
                )
            }
        ),
    )


def test_dumper_1():
    EntityTest1 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest1"]
        .cls
    )
    e1 = EntityTest1(
        fieldOne="this is read only",
        fieldTwo="this is write only",
        fieldFour="this is a field",
        fromm="this is a field with a weird name",
    )
    e1_data = {
        "fieldTwo": "this is write only",
        "fieldFour": "this is a field",
        "from": "this is a field with a weird name",
    }
    e = APPGATE_DUMPER.dump(e1)
    assert e == e1_data
    e1_data = {
        "fieldTwo": "this is write only",
        "fieldFour": "this is a field",
        "from": "this is a field with a weird name",
    }
    e = K8S_DUMPER.dump(e1)
    assert e == e1_data


def test_dumper_2():
    """
    Test dumper with metadata
    """
    EntityTest1 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest1"]
        .cls
    )
    e1 = EntityTest1(
        fieldOne="this is read only",
        fieldTwo="this is write only",
        fieldFour="this is a field",
        appgate_metadata=AppgateMetadata(uuid="666-666-666-666-666"),
    )
    e1_data = {
        "fieldTwo": "this is write only",
        "fieldFour": "this is a field",
    }
    e = APPGATE_DUMPER.dump(e1)
    assert e == e1_data

    e2_data = {
        "fieldTwo": "this is write only",
        "fieldFour": "this is a field",
        "appgate_metadata": {"uuid": "666-666-666-666-666"},
    }
    e = K8S_DUMPER.dump(e1)
    assert e == e2_data


def test_deprecated_entity():
    EntityTest1 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest1"]
        .cls
    )
    with pytest.raises(TypeError, match=f".*unexpected keyword argument 'fieldThree'"):
        EntityTest1(
            fieldOne="this is read only",
            fieldTwo="this is write only",
            fieldThree="this is deprecated",
            fieldFour="this is a field",
        )


def test_write_only_attribute_load():
    EntityTest2 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest2"]
        .cls
    )
    e_data = {
        "fieldOne": "1234567890",
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    e = APPGATE_LOADER.load(e_data, None, EntityTest2)
    # writeOnly fields are not loaded from Appgate
    assert e.fieldOne is None
    assert e.fieldTwo is None
    assert e.fieldThree == "this is a field"
    # writeOnly fields are not compared by default
    assert e == EntityTest2(
        fieldOne="1234567890",
        fieldTwo="this is write only",
        fieldThree="this is a field",
    )

    e = K8S_LOADER.load(e_data, None, EntityTest2)
    # writeOnly fields are loaded from K8S
    assert e.fieldOne == "1234567890"
    assert e.fieldTwo == "this is write only"
    assert e.fieldThree == "this is a field"
    # writeOnly fields are not compared by default
    assert e == EntityTest2(fieldOne=None, fieldTwo=None, fieldThree="this is a field")
    assert e.appgate_metadata.passwords == {"fieldOne": "1234567890"}
    assert e.appgate_metadata.password_fields == frozenset({"fieldOne"})


def test_appgate_metadata_secrets_dump_from_appgate():
    EntityTest2 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest2"]
        .cls
    )
    e1_data = {
        "fieldThree": "this is a field",
    }
    e1 = APPGATE_LOADER.load(e1_data, None, EntityTest2)
    e2_data = {
        "fieldThree": "this is a field",
        "appgate_metadata": {
            "passwordFields": ["fieldOne"],
        },
    }
    d = K8S_DUMPER.dump(e1)
    assert d == e2_data


def test_read_only_write_only_eq():
    """
    By default readOnly and writeOnly are never compared.
    But we should load the correct data from each side (K8S or APPGATE)
    """
    EntityTest4 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest4"]
        .cls
    )
    e_data = {
        "fieldOne": "writeOnly",
        "fieldTwo": "readOnly",
    }
    e = APPGATE_LOADER.load(e_data, None, EntityTest4)
    assert e == EntityTest4(fieldOne=None, fieldTwo="readOnly")
    e = APPGATE_LOADER.load(e_data, None, EntityTest4)
    assert e == EntityTest4(fieldOne=None, fieldTwo="----")
    assert e.fieldTwo == "readOnly"
    assert e.fieldOne is None

    e = K8S_LOADER.load(e_data, None, EntityTest4)
    assert e == EntityTest4(fieldOne="writeOnly", fieldTwo=None)

    e = K8S_LOADER.load(e_data, None, EntityTest4)
    assert e == EntityTest4(fieldOne="-----", fieldTwo=None)
    assert e.fieldOne == "writeOnly"
    assert e.fieldTwo is None


BASE64_FILE = """
YXBpVmVyc2lvbjogYmV0YS5hcHBnYXRlLmNvbS92MQpraW5kOiBDb25kaXRpb24KbWV0YWRhdGE6
CiAgbmFtZTogY29uZGl0aW9uLTIKc3BlYzoKICBleHByZXNzaW9uOiAnIHZhciByZXN1bHQgPSBm
YWxzZTsgLypwYXNzd29yZCovIGlmIChjbGFpbXMudXNlci5oYXNQYXNzd29yZCgnJ2NvbmRpdGlv
bi0yJycsCiAgICA2MCkpIHsgcmV0dXJuIHRydWU7IH0gLyplbmQgcGFzc3dvcmQqLyByZXR1cm4g
cmVzdWx0OyAnCiAgaWQ6IDEwMWY3OTYzLTczYjYtNDg3Mi04NTU1LWViMTVmZDk1YTYxMwogIG5h
bWU6IGNvbmRpdGlvbi0yCiAgcmVtZWR5TWV0aG9kczoKICAtIGNsYWltU3VmZml4OiB0ZXN0CiAg
ICBtZXNzYWdlOiB0ZXN0CiAgICB0eXBlOiBQYXNzd29yZEF1dGhlbnRpY2F0aW9uCiAgcmVwZWF0
U2NoZWR1bGVzOgogIC0gMWgKICAtICcxMzozMicKICB0YWdzOgogIC0gYXBpLWNyZWF0ZWQKICAt
IGF1dG9tYXRlZAogIC0gazhzCi0tLQphcGlWZXJzaW9uOiBiZXRhLmFwcGdhdGUuY29tL3YxCmtp
bmQ6IENvbmRpdGlvbgptZXRhZGF0YToKICBuYW1lOiBBbHdheXMKc3BlYzoKICBleHByZXNzaW9u
OiByZXR1cm4gdHJ1ZTsKICBpZDogZWU3YjdlNmYtZTkwNC00YjRmLWE1ZWMtYjNiZWYwNDA2NDNl
CiAgbmFtZTogQWx3YXlzCiAgbm90ZXM6IENvbmRpdGlvbiBmb3IgYnVpbHQtaW4gdXNhZ2UuCiAg
cmVtZWR5TWV0aG9kczogW10KICByZXBlYXRTY2hlZHVsZXM6IFtdCiAgdGFnczoKICAtIGJ1aWx0
aW4KLS0tCmFwaVZlcnNpb246IGJldGEuYXBwZ2F0ZS5jb20vdjEKa2luZDogQ29uZGl0aW9uCm1l
dGFkYXRhOgogIG5hbWU6IGNvbmRpdGlvbi0zCnNwZWM6CiAgZXhwcmVzc2lvbjogJyB2YXIgcmVz
dWx0ID0gZmFsc2U7IC8qcGFzc3dvcmQqLyBpZiAoY2xhaW1zLnVzZXIuaGFzUGFzc3dvcmQoJydj
b25kaXRpb24tMycnLAogICAgNjApKSB7IHJldHVybiB0cnVlOyB9IC8qZW5kIHBhc3N3b3JkKi8g
cmV0dXJuIHJlc3VsdDsgJwogIGlkOiAwOTY3MWNhNi0wNGM4LTRjMWYtOTVjMS1jZDQ3Y2VkMTI4
ZjcKICBuYW1lOiBjb25kaXRpb24tMwogIHJlbWVkeU1ldGhvZHM6IFtdCiAgcmVwZWF0U2NoZWR1
bGVzOgogIC0gMWgKICAtICcxMzozMicKICB0YWdzOgogIC0gYXBpLWNyZWF0ZWQKICAtIGF1dG9t
YXRlZAogIC0gazhzCi0tLQphcGlWZXJzaW9uOiBiZXRhLmFwcGdhdGUuY29tL3YxCmtpbmQ6IENv
bmRpdGlvbgptZXRhZGF0YToKICBuYW1lOiBjb25kaXRpb24tMQpzcGVjOgogIGV4cHJlc3Npb246
ICcgdmFyIHJlc3VsdCA9IGZhbHNlOyAvKnBhc3N3b3JkKi8gaWYgKGNsYWltcy51c2VyLmhhc1Bh
c3N3b3JkKCcnY29uZGl0aW9uLTEnJywKICAgIDYwKSkgeyByZXR1cm4gdHJ1ZTsgfSAvKmVuZCBw
YXNzd29yZCovIHJldHVybiByZXN1bHQ7ICcKICBpZDogZDQwODNkMTAtNzRkOC00OTc5LThhMGEt
ZTE5M2Q1MmQ3OThjCiAgbmFtZTogY29uZGl0aW9uLTEKICByZW1lZHlNZXRob2RzOiBbXQogIHJl
cGVhdFNjaGVkdWxlczoKICAtIDFoCiAgLSAnMTM6MzInCiAgdGFnczoKICAtIGFwaS1jcmVhdGVk
CiAgLSBhdXRvbWF0ZWQKICAtIGs4cwoK
"""
BASE64_FILE_W0 = "".join(BASE64_FILE.split("\n"))
SHA256_FILE = "0d373afdccb82399b29ba0d6d1a282b4d10d7e70d948257e75c05999f0be9f3e"
SIZE_FILE = 1563


def test_bytes_load():
    EntityTest3 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest3"]
        .cls
    )
    # fieldOne is writeOnly :: byte
    # fieldTwo is readOnly :: checksum of fieldOne
    e_data = {
        "fieldOne": BASE64_FILE_W0,
        "fieldTwo": SHA256_FILE,
    }
    # writeOnly with format bytes is never read from APPGATE
    # readOnly associated as checksum to writeOnly bytes is always read from APPGATE
    e = APPGATE_LOADER.load(e_data, None, EntityTest3)
    assert e.fieldOne is None
    assert e.fieldTwo == SHA256_FILE
    assert e == EntityTest3(fieldTwo=SHA256_FILE)
    # writeOnly bytes is never compared
    assert e == EntityTest3(fieldOne="Some value", fieldTwo=SHA256_FILE)
    # readOnly associated to writeOnly bytes is compared
    assert e != EntityTest3(fieldOne="Some value", fieldTwo="22222")

    e_data = {
        "fieldOne": BASE64_FILE_W0,
        "fieldTwo": None,
    }
    e = K8S_LOADER.load(e_data, None, EntityTest3)
    # When reading from K8S the checksum field associated to bytes is computed
    # by the operator
    assert e.fieldOne == BASE64_FILE_W0
    assert e.fieldTwo == SHA256_FILE
    # We never compare the bytes field itself, only the associated checksum field
    assert e == EntityTest3(fieldOne=None, fieldTwo=SHA256_FILE, fieldThree=SIZE_FILE)
    assert e != EntityTest3(
        fieldOne=BASE64_FILE_W0, fieldTwo="1111111", fieldThree=SIZE_FILE
    )
    assert e != EntityTest3(
        fieldOne=BASE64_FILE_W0, fieldTwo=SHA256_FILE, fieldThree=666
    )


def test_bytes_dump():
    EntityTest3 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest3"]
        .cls
    )
    e = EntityTest3(fieldOne=BASE64_FILE_W0, fieldTwo=SHA256_FILE)
    e_data = {"fieldOne": BASE64_FILE_W0}
    # We don't dump the checksum field associated to bytes to APPGATE
    assert APPGATE_DUMPER.dump(e) == e_data
    e = EntityTest3(fieldOne=BASE64_FILE_W0)
    assert APPGATE_DUMPER.dump(e) == e_data
    e = EntityTest3(fieldTwo=SHA256_FILE)
    assert APPGATE_DUMPER.dump(e) == {}

    e = EntityTest3(fieldOne=BASE64_FILE_W0, fieldTwo=SHA256_FILE)
    e_data = {
        "fieldOne": BASE64_FILE_W0,
    }
    # We don't dump the checksum field associated to bytes to K8S
    assert K8S_DUMPER.dump(e) == e_data


def test_bytes_diff_dump():
    # DIFF mode we should dump just the fields used for equality
    EntityTest3Appgate = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest3Appgate"]
        .cls
    )
    appgate_metadata = {"uuid": "6a01c585-c192-475b-b86f-0e632ada6769"}
    e_data = {
        "name": "entity1",
        "fieldOne": BASE64_FILE_W0,
        "fieldTwo": None,
        "fieldThree": None,
        "appgate_metadata": appgate_metadata,
    }

    e = K8S_LOADER.load(e_data, None, EntityTest3Appgate)
    assert DIFF_DUMPER.dump(e) == {
        "name": "entity1",
        "fieldTwo": SHA256_FILE,
        "fieldThree": SIZE_FILE,
    }


def test_certificate_pem_load():
    EntityCert = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityCert"]
        .cls
    )
    EntityCert_Fieldtwo = (
        load_test_open_api_spec(secrets_key=None).entities["EntityCert_Fieldtwo"].cls
    )
    cert = EntityCert_Fieldtwo(
        version=1,
        serial="3578",
        issuer=join_string(ISSUER),
        subject=join_string(SUBJECT),
        validFrom=datetime.datetime(
            2012, 8, 22, 5, 26, 54, tzinfo=datetime.timezone.utc
        ),
        validTo=datetime.datetime(2017, 8, 21, 5, 26, 54, tzinfo=datetime.timezone.utc),
        fingerprint=FINGERPRINT,
        certificate=join_string(CERTIFICATE_FIELD),
        subjectPublicKey=join_string(PUBKEY_FIELD),
    )

    e0_data = {
        "fieldOne": PEM_TEST,
        "fieldTwo": {
            "version": 1,
            "serial": "3578",
            "issuer": join_string(ISSUER),
            "subject": join_string(SUBJECT),
            "validFrom": "2012-08-22T05:26:54.000Z",
            "validTo": "2017-08-21T05:26:54.000Z",
            "fingerprint": FINGERPRINT,
            "certificate": join_string(CERTIFICATE_FIELD),
            "subjectPublicKey": join_string(PUBKEY_FIELD),
        },
    }
    e0 = APPGATE_LOADER.load(e0_data, None, EntityCert)
    assert (
        e0.fieldOne
        == """\
-----BEGIN CERTIFICATE-----
MIICEjCCAXsCAg36MA0GCSqGSIb3DQEBBQUAMIGbMQswCQYDVQQGEwJKUDEOMAwG
A1UECBMFVG9reW8xEDAOBgNVBAcTB0NodW8ta3UxETAPBgNVBAoTCEZyYW5rNERE
MRgwFgYDVQQLEw9XZWJDZXJ0IFN1cHBvcnQxGDAWBgNVBAMTD0ZyYW5rNEREIFdl
YiBDQTEjMCEGCSqGSIb3DQEJARYUc3VwcG9ydEBmcmFuazRkZC5jb20wHhcNMTIw
ODIyMDUyNjU0WhcNMTcwODIxMDUyNjU0WjBKMQswCQYDVQQGEwJKUDEOMAwGA1UE
CAwFVG9reW8xETAPBgNVBAoMCEZyYW5rNEREMRgwFgYDVQQDDA93d3cuZXhhbXBs
ZS5jb20wXDANBgkqhkiG9w0BAQEFAANLADBIAkEAm/xmkHmEQrurE/0re/jeFRLl
8ZPjBop7uLHhnia7lQG/5zDtZIUC3RVpqDSwBuw/NTweGyuP+o8AG98HxqxTBwID
AQABMA0GCSqGSIb3DQEBBQUAA4GBABS2TLuBeTPmcaTaUW/LCB2NYOy8GMdzR1mx
8iBIu2H6/E2tiY3RIevV2OW61qY2/XRQg7YPxx3ffeUugX9F4J/iPnnu1zAxxyBy
2VguKv4SWjRFoRkIfIlHX0qVviMhSlNy2ioFLy7JcPZb+v3ftDGywUqcBiVDoea0
Hn+GmxZA
-----END CERTIFICATE-----"""
    )
    assert e0.fieldTwo == cert

    e1_data = {
        "fieldOne": PEM_TEST,
    }

    e1 = K8S_LOADER.load(e1_data, None, EntityCert)
    assert e1.fieldOne == PEM_TEST
    assert e1.fieldTwo == cert
    assert e1 == EntityCert(fieldOne=e0.fieldOne, fieldTwo=cert)
    assert e1 == e0

    cert2 = EntityCert_Fieldtwo(
        version=1,
        serial="3578",
        issuer=join_string(ISSUER),
        subject=join_string(SUBJECT),
        validFrom=datetime.datetime(
            2017, 3, 6, 16, 50, 58, 516000, tzinfo=datetime.timezone.utc
        ),
        validTo=datetime.datetime(
            2025, 3, 6, 16, 50, 58, 516000, tzinfo=datetime.timezone.utc
        ),
        fingerprint=FINGERPRINT,
        certificate=join_string(CERTIFICATE_FIELD),
        subjectPublicKey=join_string(PUBKEY_FIELD),
    )
    e2 = EntityCert(fieldOne="foobar", fieldTwo=cert2)
    assert e1 != e2

    e2_dumped = DIFF_DUMPER.dump(e2)
    # Just check that it's dumped properly
    assert e2_dumped["fieldOne"] == "foobar"
    assert e2_dumped["fieldTwo"]["validFrom"] == "2017-03-06T16:50:58.516Z"
