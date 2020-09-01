from typing import Dict, List, Union

from appgate.customloaders import CustomAttribLoader

__all__ = [
    'PasswordAttribMaker'
]

from appgate.openapi import OpenApiDict, SimpleAttribMaker, AttributesDict

PasswordField = Union[str, OpenApiDict]


class AppgateSecretException(Exception):
    pass


def decrypt_password():
    key = 'not implemented'
    def _decrypt_password(value: str):
        return value

    return _decrypt_password


class AppgateSecret:
    """
    AppgateSecret base abstract class. Every password field in an entity will
    be an AppgateSecret instance that will be able to decrypt its value.
    """
    def __init__(self, value: PasswordField) -> None:
        self.value = value

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
            return self.value
        raise AppgateSecretException('AppgateSecretSimple must be a string')

    def decrypt(self) -> str:
        # Get secret from k8s secret
        return self._get_encrypted_password()


class AppgateSecretK8SSimple(AppgateSecret):
    """
    AppgateSecretK8SSecretSimple:
    Password field is stored as a K8S secret.
    The password field specifies the secret where to get the password
    from.
    """
    def _get_encrypted_password(self) -> str:
        if isinstance(self.value, str):
            return self.value
        raise AppgateSecretException('AppgateSecretSimple must be a string')

    def decrypt(self) -> str:
        # Get secret from k8s secret
        return self._get_encrypted_password()


class AppgateSecretK8SKey(AppgateSecret):
    """
    AppgateSecretK8SSecretKey:
    Password field is decrypted using a key that is store as a K8S secret.
    The password field specifies where the secret in which the key is
    stored.
    """
    def _get_encrypted_password(self) -> str:
        if isinstance(self.value, str):
            return self.value
        raise AppgateSecretException('AppgateSecretSimple must be a string')

    def decrypt(self) -> str:
        # Get key from k8s secret and use it to decrypt
        return self._get_encrypted_password()


def get_appgate_secret(value: PasswordField) -> AppgateSecret:
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
            return AppgateSecretK8SSimple(value)
        elif value.get('type') == 'k8s/secret-key':
            return AppgateSecretK8SKey(value)
        else:
            raise AppgateSecretException('Unable to determine AppgateSecret format from %s.',
                                         value)
    elif isinstance(value, str):
        return AppgateSecretSimple(value)


def appgate_secret_load(value: OpenApiDict) -> str:
    appgate_secret = get_appgate_secret(value)
    return appgate_secret.decrypt()


class PasswordAttribMaker(SimpleAttribMaker):
    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = instance_maker_config.compare_secrets
        if 'metadata' not in values:
            values['metadata'] = {}
        values['metadata']['k8s_loader'] = CustomAttribLoader(
            loader=lambda v: appgate_secret_load(v),
            field=self.name,
        )
        return values
