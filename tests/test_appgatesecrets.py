import os
from unittest.mock import patch

import pytest

from appgate.attrs import (
    APPGATE_LOADER,
    K8S_LOADER,
    K8S_DUMPER,
    APPGATE_DUMPER,
)
from appgate.secrets import (
    get_appgate_secret,
    AppgateSecretSimple,
    AppgateSecretK8S,
    AppgateSecretException,
    AppgateSecretPlainText,
    AppgateVaultSecret,
)
from appgate.types import EntityWrapper
from appgate.openapi.types import AppgateTypedloadException
from tests.utils import (
    load_test_open_api_spec,
    ENCRYPTED_PASSWORD,
    FERNET_CIPHER,
    KEY,
    _k8s_get_secret,
)


def test_write_only_password_attribute_dump():
    api_spec = load_test_open_api_spec(reload=True)
    EntityTest2 = api_spec.entities["EntityTest2"].cls
    e = EntityTest2(
        fieldOne="1234567890",
        fieldTwo="this is write only",
        fieldThree="this is a field",
    )
    e_data = {
        "fieldOne": "1234567890",
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    assert K8S_DUMPER(api_spec).dump(e, False) == {
        "apiVersion": "v666.sdp.appgate.com/v1",
        "kind": "EntityTest2",
        "metadata": {
            "name": "entitytest2",
            "annotations": {},
        },
        "spec": e_data,
    }
    assert APPGATE_DUMPER.dump(e, False) == e_data


def test_write_only_password_attribute_load():
    e_data = {
        "name": "test_write_only_password_attribute_load",
        "fieldOne": ENCRYPTED_PASSWORD,  # password
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    EntityTest2 = load_test_open_api_spec(reload=True).entities["EntityTest2"].cls

    e = APPGATE_LOADER.load(e_data, None, EntityTest2)
    # writeOnly passwords are not loaded from Appgate
    assert e.fieldOne is None
    assert e.fieldTwo is None
    assert e.fieldThree == "this is a field"
    assert e.fieldThree == "this is a field"
    # writeOnly passwords are not compared
    assert e == EntityTest2(
        fieldOne="wrong-password", fieldTwo="some value", fieldThree="this is a field"
    )
    # normal fields are compared
    assert e != EntityTest2(
        fieldOne=None,
        fieldTwo=None,
        fieldThree="this is a field with a different value",
    )

    # normal writeOnly fields are not compared when compare_secrets is True
    assert e == EntityTest2(
        fieldOne=None, fieldTwo="some value", fieldThree="this is a field"
    )

    e = K8S_LOADER.load(e_data, None, EntityTest2)
    # writeOnly password fields are loaded from K8S
    assert e.fieldOne == "1234567890"  # decrypted password
    assert e.fieldTwo == "this is write only"
    assert e.fieldThree == "this is a field"
    # writeOnly password fields are not compared by default
    assert e == EntityTest2(fieldOne=None, fieldTwo=None, fieldThree="this is a field")
    assert e != EntityTest2(
        fieldOne=None,
        fieldTwo=None,
        fieldThree="this is a field with a different value",
    )


def test_get_appgate_secret_plain_text():
    value = "aaaaaa"
    secret = get_appgate_secret(
        value, None, lambda x: ENCRYPTED_PASSWORD, "entity1", "field1", ()
    )
    assert isinstance(secret, AppgateSecretPlainText)


def test_get_appgate_secret_simple():
    value = "aaaaaa"
    secret = get_appgate_secret(
        value, FERNET_CIPHER, lambda x: ENCRYPTED_PASSWORD, "entity1", "field1", ()
    )
    assert isinstance(secret, AppgateSecretSimple)


def test_get_appgate_secret_k8s_simple():
    value = {"type": "k8s/secret", "password": "secret1"}
    secret = get_appgate_secret(
        value, FERNET_CIPHER, lambda x: ENCRYPTED_PASSWORD, "entity1", "field1", ()
    )
    assert isinstance(secret, AppgateSecretK8S)


def exception():
    value = {"some": "value"}
    with pytest.raises(AppgateSecretException):
        get_appgate_secret(
            value, FERNET_CIPHER, lambda x: ENCRYPTED_PASSWORD, "", "", ()
        )


def test_get_appgate_secret_simple_load():
    EntityTest2 = (
        load_test_open_api_spec(secrets_key=KEY, reload=True)
        .entities["EntityTest2"]
        .cls
    )
    data = {
        "fieldOne": ENCRYPTED_PASSWORD,
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    e = K8S_LOADER.load(data, None, EntityTest2)
    # Password is decrypted
    assert e.fieldOne == "1234567890"
    assert e.appgate_metadata.passwords == {"fieldOne": ENCRYPTED_PASSWORD}


def test_get_appgate_secret_simple_load_no_cipher():
    EntityTest2 = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTest2"]
        .cls
    )
    data = {
        "fieldOne": ENCRYPTED_PASSWORD,
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    e = K8S_LOADER.load(data, None, EntityTest2)
    # We don't try to decrypt the password, use it as we get it
    assert e.fieldOne == ENCRYPTED_PASSWORD
    assert e.appgate_metadata.passwords == {"fieldOne": ENCRYPTED_PASSWORD}


def test_get_appgate_secret_k8s_simple_load():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data = {
        "name": "test_get_appgate_secret_k8s_simple_load",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    e = K8S_LOADER.load(data, None, EntityTest2)
    # Password is coming from k8s secrets
    assert e.fieldOne == "1234567890-from-k8s"
    assert e.appgate_metadata.passwords == {"fieldOne": data["fieldOne"]}


def test_get_appgate_secret_k8s_simple_load_missing_key():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data = {
        "name": "test_get_appgate_secret_k8s_simple_load_missing_key",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    with pytest.raises(AppgateTypedloadException) as exc:
        K8S_LOADER.load(data, None, EntityTest2)
    assert "Unable to get secret: secret-storage.field-one" in str(exc)


def test_get_secret_read_entity_without_password():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data = {
        "name": "test_get_secret_read_entity_without_password",
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    e = K8S_LOADER.load(data, None, EntityTest2)
    # Password is coming from k8s secrets
    assert e.fieldOne is None


def test_compare_entity_with_secrets():
    """
    If we are missing metadata frm k8s we should always update the entity
    """
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data_1 = {
        "name": "test_compare_entity_with_secrets",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    data_2 = {
        "name": "test_compare_entity_with_secrets",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-10T12:20:14Z",
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, None, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))
    assert e1 != e2


def test_compare_entity_with_secrets_with_metadata_1():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data_1 = {
        "name": "test_compare_entity_with_secrets_with_metadata_1",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    data_2 = {
        "name": "test_compare_entity_with_secrets_with_metadata_1",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-10T12:20:14Z",
    }

    appgate_metadata = {
        "generation": 1,
        "latestGeneration": 1,
        "creationTimestamp": "2020-09-10T10:20:14Z",
        "modificationTimestamp": "2020-09-09T12:20:14Z",
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, appgate_metadata, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))

    assert e1 == e2

    data_2 = {
        "name": "test_compare_entity_with_secrets_with_metadata_1",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field different",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-08T12:20:14Z",
    }
    e3 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))
    assert e1 != e3


def test_compare_entity_with_secrets_with_metadata_2():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data_1 = {
        "name": "test_compare_entity_with_secrets_with_metadata_2",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    data_2 = {
        "name": "test_compare_entity_with_secrets_with_metadata_2",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-10T12:20:14Z",
    }
    appgate_metadata = {
        "generation": 1,
        "latestGeneration": 1,
        "creationTimestamp": "2020-09-10T10:20:14Z",
        "modificationTimestamp": "2020-09-16T12:20:14Z",
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, appgate_metadata, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))
    assert e1 != e2


def test_compare_entity_with_secrets_with_metadata_3():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data_1 = {
        "name": "test_compare_entity_with_secrets_with_metadata_3",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    data_2 = {
        "name": "test_compare_entity_with_secrets_with_metadata_3",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-10T12:20:14Z",
    }
    appgate_metadata = {
        "generation": 2,
        "latestGeneration": 1,
        "creationTimestamp": "2020-09-10T10:20:14Z",
        "modificationTimestamp": "2020-09-10T12:20:14Z",
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, appgate_metadata, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))
    assert e1 != e2


def test_compare_entity_with_secrets_with_metadata_4():
    EntityTest2 = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )
    data_1 = {
        "name": "test_compare_entity_with_secrets_with_metadata_4",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }
    data_2 = {
        "name": "test_compare_entity_with_secrets_with_metadata_4",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-20T12:20:14Z",
    }
    appgate_metadata = {
        "generation": 2,
        "latestGeneration": 3,
        "creationTimestamp": "2020-09-10T10:20:14Z",
        "modificationTimestamp": "2020-09-20T12:19:14Z",
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, appgate_metadata, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))
    assert e1 == e2


def test_compare_entity_without_secrets_and_metadata():
    EntityTest2WihoutPassword = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2WihoutPassword"]
        .cls
    )
    data_1 = {
        "name": "test_compare_entity_without_secrets_and_metadata",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-10T12:20:14Z",
    }
    data_2 = {
        "name": "test_compare_entity_without_secrets_and_metadata",
        "fieldOne": {
            "type": "k8s/secret",
            "name": "secret-storage-1",
            "key": "field-one",
        },
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
        "created": "2020-09-10T12:20:14Z",
        "updated": "2020-09-10T12:20:14Z",
    }
    appgate_metadata = {
        "generation": 2,
        "latestGeneration": 1,
        "creationTimestamp": "2020-09-10T10:20:14Z",
        "modificationTimestamp": "2020-09-10T12:20:14Z",
    }
    e1 = EntityWrapper(
        K8S_LOADER.load(data_1, appgate_metadata, EntityTest2WihoutPassword)
    )
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2WihoutPassword))
    assert e1 == e2


@patch.dict(os.environ, {"APPGATE_SECRET_SOURCE": "vault"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_vault_secret():
    EntityTest = (
        load_test_open_api_spec(reload=True, k8s_get_secret=_k8s_get_secret)
        .entities["EntityTest2"]
        .cls
    )

    data_without_password = {
        "name": "vault_secret_foo",
        "fieldTwo": "this is write only",
        "fieldThree": "this is a field",
    }

    ret = {
        "data": {"data": {"entitytest2-v18/vault_secret_foo/fieldOne": "1234567890"}}
    }

    with patch.object(AppgateVaultSecret, "authenticate"), patch.object(
        AppgateVaultSecret, "read_secret_from_vault", return_value=ret
    ) as read_secret_from_vault:
        e = K8S_LOADER.load(data_without_password, None, EntityTest)
        read_secret_from_vault.assert_called()
        assert e.fieldOne == "1234567890"


@patch.dict(os.environ, {"APPGATE_SECRET_SOURCE": "vault"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_vault_secret_2():
    EntityTestSecret = (
        load_test_open_api_spec(reload=True).entities["EntityTestSecret"].cls
    )

    # Data does not contain field referenced in x-password-key
    # Use the field name as the URL Key
    data = {"name": "test-entity-secret1"}
    ret = {
        "data": {
            "data": {"entitytestsecret-v18/test-entity-secret1/password": "1234567890"}
        }
    }

    with patch.object(AppgateVaultSecret, "authenticate"), patch.object(
        AppgateVaultSecret, "read_secret_from_vault", return_value=ret
    ) as read_secret_from_vault:
        e = K8S_LOADER.load(data, None, EntityTestSecret)
        read_secret_from_vault.assert_called()
        assert e.password == "1234567890"

    # Data contains field referenced in x-password-key
    # Use the field name as the URL Key
    data = {"name": "test-entity-secret1", "fieldOne": "password-is-here"}
    ret = {"data": {"data": {"entitytestsecret-v18/password-is-here": "1234567890"}}}

    with patch.object(AppgateVaultSecret, "authenticate"), patch.object(
        AppgateVaultSecret, "read_secret_from_vault", return_value=ret
    ) as read_secret_from_vault:
        e = K8S_LOADER.load(data, None, EntityTestSecret)
        read_secret_from_vault.assert_called()
        assert e.password == "1234567890"


def test_load_vault_secret_nested():
    EntityTestSecret = (
        load_test_open_api_spec(reload=True).entities["EntityTestSecretNested"].cls
    )

    data = {
        "name": "test-entity-secret1",
        "passwordList": [{"fieldOne": "array-item-1"}, {"fieldOne": "array-item-2"}],
    }

    ret = {
        "data": {
            "data": {"entitytestsecret-v18/test-entity-secret1/password": "1234567890"}
        }
    }

    with patch.object(AppgateVaultSecret, "authenticate"), patch.object(
        AppgateVaultSecret, "read_secret_from_vault", return_value=ret
    ) as read_secret_from_vault:
        e = K8S_LOADER.load(data, None, EntityTestSecret)
        read_secret_from_vault.assert_called()
        assert e.password == "1234567890"
