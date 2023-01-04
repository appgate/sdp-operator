import base64
import os
from typing import Dict, List, Union, Optional, Callable

from attr import evolve

from cryptography.fernet import Fernet
from hvac import Client  # type: ignore
from hvac.api.auth_methods import Kubernetes  # type: ignore
from kubernetes.client import CoreV1Api

from appgate.customloaders import (
    CustomEntityLoader,
    CustomAttribLoader,
)
from appgate.logger import log
from appgate.openapi.attribmaker import AttribMaker
from appgate.openapi.types import (
    AttribType,
    OpenApiDict,
    AttributesDict,
    EntityClassGeneratorConfig,
    K8S_LOADERS_FIELD_NAME,
    Entity_T,
    APPGATE_LOADERS_FIELD_NAME,
)
from appgate.openapi.utils import get_passwords


__all__ = [
    "PasswordAttribMaker",
    "get_appgate_secret",
    "AppgateSecretK8S",
    "AppgateSecretException",
    "AppgateSecretPlainText",
    "AppgateSecretSimple",
    "k8s_get_secret",
]


PasswordField = Union[str, OpenApiDict]

APPGATE_SECRET_SOURCE_ENV = "APPGATE_SECRET_SOURCE"


class AppgateSecretException(Exception):
    pass


class AppgateSecret:
    """
    AppgateSecret base abstract class. Every password field in an entity will
    be an AppgateSecret instance that will be able to decrypt its value.
    """

    def __init__(self, value: PasswordField) -> None:
        self.value = value

    def decrypt(self) -> str:
        raise NotImplementedError()

    @staticmethod
    def isinstance(value: PasswordField) -> bool:
        raise NotImplementedError()


class AppgateSecretPlainText(AppgateSecret):
    """
    AppgateSecretSimple:
    Implements the most basic of the secrets.
    Plain text passwords in the fields.
    """

    def decrypt(self) -> str:
        if not isinstance(self.value, str):
            raise AppgateSecretException("AppgateSecretPlainText must be a string")
        return self.value

    @staticmethod
    def isinstance(value: PasswordField) -> bool:
        return isinstance(value, str)


class AppgateSecretSimple(AppgateSecret):
    """
    AppgateSecretSimple:
    Implements a basic encrypted.
    The password field is encrypted using a PrivateKey that is stored
    in an environment variable.
    """

    def __init__(self, value: PasswordField, secrets_cipher: Fernet) -> None:
        super().__init__(value)
        self.value = value
        self.secrets_cipher = secrets_cipher

    def decrypt(self) -> str:
        if not isinstance(self.value, str):
            raise AppgateSecretException("AppgateSecretSimple must be a string")
        return self.secrets_cipher.decrypt(self.value.encode()).decode()

    @staticmethod
    def isinstance(value: PasswordField) -> bool:
        return isinstance(value, str)


class AppgateSecretK8S(AppgateSecret):
    """
    AppgateSecretK8SSecretSimple:
    Password field is stored as a K8S secret.
    The password field specifies the secret where to get the password
    from.
    """

    def __init__(
        self, value: PasswordField, k8s_get_client: Callable[[str, str], str]
    ) -> None:
        super().__init__(value)
        self.value = value
        self.k8s_get_client = k8s_get_client

    def decrypt(self) -> str:
        if not isinstance(self.value, dict):
            raise AppgateSecretException("AppgateSecretK8S must be a dictionary")
        secret = self.value.get("name")
        key = self.value.get("key")
        if not secret:
            raise AppgateSecretException("AppgateSecretK8S missing field secret")
        if not key:
            raise AppgateSecretException("AppgateSecretK8S missing field key")
        return self.k8s_get_client(secret, key)

    @staticmethod
    def isinstance(value: PasswordField) -> bool:
        return isinstance(value, dict) and value.get("type") == "k8s/secret"


class AppgateVaultSecret(AppgateSecret):
    def __init__(self, value: PasswordField, entity_name: str) -> None:
        super().__init__(value)
        self.entity_name = entity_name
        self.api_version = os.getenv("APPGATE_API_VERSION")

        address = os.getenv("APPGATE_VAULT_ADDRESS", "localhost")
        jwt = open("/var/run/secrets/kubernetes.io/serviceaccount/token").read()
        self.vault_client = Client(url=address)
        Kubernetes(self.vault_client.adapter).login(role="sdp-operator", jwt=jwt)

    def decrypt(self) -> str:
        response = self.vault_client.secrets.kv.read_secret_version(path="sdp")

        if isinstance(self.value, Dict):
            field_name = self.value.get("name")
        else:
            log.warning("Unable to get the field name from the values: %s", self.value)
            return ""

        pw_key = f"{self.entity_name.lower()}-{self.api_version}/{field_name}"
        pw_value: str = response["data"]["data"].get(pw_key, "")

        if not pw_value:
            log.warning("Unable to fetch the password from vault for entity %s", pw_key)

        return pw_value

    @staticmethod
    def isinstance(_: PasswordField) -> bool:
        return os.getenv(APPGATE_SECRET_SOURCE_ENV, "") == "vault"


def get_appgate_secret(
    value: PasswordField,
    secrets_cipher: Optional[Fernet],
    k8s_get_client: Optional[Callable[[str, str], str]],
    entity_name: str,
) -> AppgateSecret:
    """
    Retuns an AppgateSecret from a password field value.
    value can be:
      - str -> AppgateSecretSimple
      - dict:
        - AppgateSecretK8SSecretSimple
          {'type': 'k8s/secret', 'password': 'secret1'}
    """
    if AppgateSecretK8S.isinstance(value):
        if not k8s_get_client:
            raise AppgateSecretException(
                "AppgateSecretK8S found but not k8s client found."
            )
        return AppgateSecretK8S(value, k8s_get_client=k8s_get_client)
    elif AppgateSecretSimple.isinstance(value) and secrets_cipher:
        return AppgateSecretSimple(value, secrets_cipher)
    elif AppgateSecretSimple.isinstance(value):
        return AppgateSecretPlainText(value)
    elif AppgateVaultSecret.isinstance(value):
        return AppgateVaultSecret(value, entity_name)
    raise AppgateSecretException("Unable to create an AppgateSecret from %s.", value)


def appgate_secret_load(
    value: OpenApiDict,
    secrets_cipher: Optional[Fernet],
    k8s_get_client: Optional[Callable[[str, str], str]],
    entity_name: str,
) -> str:
    appgate_secret = get_appgate_secret(
        value, secrets_cipher, k8s_get_client, entity_name
    )
    return appgate_secret.decrypt()


class PasswordAttribMaker(AttribMaker):
    def __init__(
        self,
        name: str,
        tpe: type,
        base_tpe: type,
        default: Optional[AttribType],
        factory: Optional[type],
        definition: OpenApiDict,
        secrets_cipher: Optional[Fernet],
        k8s_get_client: Optional[Callable[[str, str], str]],
    ) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.secrets_cipher = secrets_cipher
        self.k8s_get_client = k8s_get_client

    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: "EntityClassGeneratorConfig",
    ) -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values["eq"] = False

        # sets appgate_metadata.passwords
        # TODO: Recursive fields
        def set_appgate_password_metadata(orig_values, entity: Entity_T) -> Entity_T:
            password_fields = get_passwords(entity)
            orig_passwords = {}
            field_passwords = []
            for field in password_fields:
                field_passwords.append(field)
                if field in orig_values:
                    orig_passwords[field] = orig_values[field]
            appgate_mt = entity.appgate_metadata.with_password_fields(
                field_passwords
            ).with_password_values(orig_passwords)
            return evolve(entity, appgate_metadata=appgate_mt)

        if "metadata" not in values:
            values["metadata"] = {}
        values["metadata"][K8S_LOADERS_FIELD_NAME] = [
            CustomAttribLoader(
                loader=lambda v: appgate_secret_load(
                    v,
                    self.secrets_cipher,
                    self.k8s_get_client,
                    instance_maker_config.entity_name,
                ),
                field=self.name,
                load_external="APPGATE_SECRET_SOURCE" in os.environ,
            ),
            CustomEntityLoader(loader=set_appgate_password_metadata),
        ]
        values["metadata"][APPGATE_LOADERS_FIELD_NAME] = [
            CustomEntityLoader(loader=set_appgate_password_metadata)
        ]
        return values

    @property
    def is_password(self) -> bool:
        return True


def k8s_get_secret(namespace: str, secret: str, key: str) -> str:
    """
    Gets a secret from k8s
    """
    v1 = CoreV1Api()
    resp = v1.read_namespaced_secret(name=secret, namespace=namespace)
    data = resp.data
    k8s_secret = data.get(key)
    if not k8s_secret:
        raise AppgateSecretException(
            f"Unable to get secret {secret}.{key} " f"from namespace {namespace}"
        )
    return base64.b64decode(k8s_secret).decode()
