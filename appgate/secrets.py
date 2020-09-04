import base64
from typing import Dict, List, Union, Optional, Callable

from appgate.customloaders import CustomAttribLoader
from appgate.openapi.attribmaker import SimpleAttribMaker
from appgate.openapi.types import AttribType, OpenApiDict, AttributesDict, InstanceMakerConfig

from cryptography.fernet import Fernet
from kubernetes.client import CoreV1Api


__all__ = [
    'PasswordAttribMaker',
    'get_appgate_secret',
    'AppgateSecretK8S',
    'AppgateSecretException',
    'AppgateSecretPlainText',
    'AppgateSecretSimple',
    'k8s_get_secret',
]


PasswordField = Union[str, OpenApiDict]


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
            raise AppgateSecretException('AppgateSecretPlainText must be a string')
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
            raise AppgateSecretException('AppgateSecretSimple must be a string')
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
    def __init__(self, value: PasswordField, k8s_get_client: Callable[[str, str], str]) -> None:
        super().__init__(value)
        self.value = value
        self.k8s_get_client = k8s_get_client

    def decrypt(self) -> str:
        if not isinstance(self.value, dict):
            raise AppgateSecretException('AppgateSecretK8S must be a dictionary')
        secret = self.value.get('name')
        key = self.value.get('key')
        if not secret:
            raise AppgateSecretException('AppgateSecretK8S missing field secret')
        if not key:
            raise AppgateSecretException('AppgateSecretK8S missing field key')
        return self.k8s_get_client(secret, key)

    @staticmethod
    def isinstance(value: PasswordField) -> bool:
        return isinstance(value, dict) and value.get('type') == 'k8s/secret'


def get_appgate_secret(value: PasswordField, secrets_cipher: Optional[Fernet],
                       k8s_get_client: Optional[Callable[[str, str], str]]) -> AppgateSecret:
    """
    Retuns an AppgateSecret from a password field value.
    value can be:
      - str -> AppgateSecretSimple
      - dict:
        - AppgateSecretK8SSecretSimple
          {'type': 'k8s/secret', 'password': 'secret1'}
        - AppgateSecretK8SSecretKey
          {'type': 'k8s/secret-key', 'key': 'secret1'}
    """
    if AppgateSecretK8S.isinstance(value):
        if not k8s_get_client:
            raise AppgateSecretException('AppgateSecretK8S found but not k8s client found.')
        return AppgateSecretK8S(value, k8s_get_client=k8s_get_client)
    elif AppgateSecretSimple.isinstance(value) and secrets_cipher:
        return AppgateSecretSimple(value, secrets_cipher)
    elif AppgateSecretSimple.isinstance(value):
        return AppgateSecretPlainText(value)
    raise AppgateSecretException('Unable to create an AppgateSecret from %s.', value)


def appgate_secret_load(value: OpenApiDict, secrets_cipher: Optional[Fernet],
                        k8s_get_client: Optional[Callable[[str, str], str]]) -> str:
    appgate_secret = get_appgate_secret(value, secrets_cipher, k8s_get_client=k8s_get_client)
    return appgate_secret.decrypt()


class PasswordAttribMaker(SimpleAttribMaker):
    def __init__(self, name: str, tpe: type, base_tpe: type, default: Optional[AttribType],
                 factory: Optional[type], definition: OpenApiDict,
                 secrets_cipher: Optional[Fernet],
                 k8s_get_client: Optional[Callable[[str, str], str]]) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.secrets_cipher = secrets_cipher
        self.k8s_get_client = k8s_get_client

    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = instance_maker_config.compare_secrets
        if 'metadata' not in values:
            values['metadata'] = {}
        values['metadata']['k8s_loader'] = CustomAttribLoader(
            loader=lambda v: appgate_secret_load(v, self.secrets_cipher, self.k8s_get_client),
            field=self.name)
        return values

    @property
    def is_password(self) -> bool:
        return True


def k8s_get_secret(namespace: str, secret: str, key: str) -> str:
    """
    Gets a secret from k8s
    """
    v1 = CoreV1Api()
    data = v1.read_namespaced_secret(secret, namespace).data
    k8s_secret = data.get(key)
    if not k8s_secret:
        raise AppgateSecretException(f'Unable to get secret {secret}.{key} '
                                     f'from namespace {namespace}')
    return base64.b64decode(k8s_secret).decode()
