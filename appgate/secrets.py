from typing import Dict, List, Union, Optional, Callable

from appgate.customloaders import CustomAttribLoader
from appgate.openapi.attribmaker import SimpleAttribMaker
from appgate.openapi.types import AttribType, OpenApiDict, AttributesDict

from cryptography.fernet import Fernet


__all__ = [
    'PasswordAttribMaker'
]


PasswordField = Union[str, OpenApiDict]


class AppgateSecretException(Exception):
    pass


class AppgateSecret:
    """
    AppgateSecret base abstract class. Every password field in an entity will
    be an AppgateSecret instance that will be able to decrypt its value.
    """
    def __init__(self, value: PasswordField, secrets_cipher: Fernet) -> None:
        self.value = value
        self.secrets_cipher = secrets_cipher

    def decrypt(self) -> str:
        raise NotImplementedError()


class AppgateSecretSimple(AppgateSecret):
    """
    AppgateSecretSimple:
    Implements the most basic of the secrets.
    The password field is encrypted using a PrivateKey that is stored
    in an environment variable.
    """
    def _get_encrypted_password(self) -> str:
        if isinstance(self.value, str):
            return self.secrets_cipher.decrypt(self.value.encode()).decode()
        raise AppgateSecretException('AppgateSecretSimple must be a string')

    def decrypt(self) -> str:
        # Get secret from k8s secret
        return self._get_encrypted_password()


class AppgateSecretK8S(AppgateSecret):
    """
    AppgateSecretK8SSecretSimple:
    Password field is stored as a K8S secret.
    The password field specifies the secret where to get the password
    from.
    """
    def __init__(self, value: PasswordField, secrets_cipher: Fernet,
                 k8s_get_client: Callable[[str, str], str]) -> None:
        super().__init__(value, secrets_cipher)
        self.value = value
        self.secrets_cipher = secrets_cipher
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


def get_appgate_secret(value: PasswordField, secrets_cipher: Fernet,
                       k8s_get_client: Callable[[str, str], str]) -> AppgateSecret:
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
    if isinstance(value, dict):
        if value.get('type') == 'k8s/secret':
            return AppgateSecretK8S(value, secrets_cipher, k8s_get_client=k8s_get_client)
        else:
            raise AppgateSecretException('Unable to create an AppgateSecret from %s.',
                                         value)
    elif isinstance(value, str):
        return AppgateSecretSimple(value, secrets_cipher)


def appgate_secret_load(value: OpenApiDict, secrets_cipher: Fernet,
                        k8s_get_client: Callable[[str, str], str]) -> str:
    appgate_secret = get_appgate_secret(value, secrets_cipher, k8s_get_client=k8s_get_client)
    return appgate_secret.decrypt()


class PasswordAttribMaker(SimpleAttribMaker):
    def __init__(self, name: str, tpe: type, default: Optional[AttribType],
                 factory: Optional[type], definition: OpenApiDict,
                 secrets_cipher: Optional[Fernet],
                 k8s_get_client: Callable[[str, str], str]) -> None:
        super().__init__(name, tpe, default, factory, definition)
        self.secrets_cipher = secrets_cipher
        self.k8s_get_client = k8s_get_client

    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = instance_maker_config.compare_secrets
        if 'metadata' not in values:
            values['metadata'] = {}
        if self.secrets_cipher:
            # If we got a cipher use it
            values['metadata']['k8s_loader'] = CustomAttribLoader(
                loader=lambda v: appgate_secret_load(v, self.secrets_cipher, self.k8s_get_client),
                field=self.name,
            )
        return values
