"""Service to manipulate Phalanx secrets."""

from __future__ import annotations

import json
from base64 import b64decode
from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import SecretStr

from ..exceptions import NoOnepasswordConfigError, UnresolvedSecretsError
from ..models.environments import Environment
from ..models.secrets import (
    PullSecret,
    ResolvedSecrets,
    Secret,
    SourceSecretGenerateRules,
    StaticSecret,
    StaticSecrets,
)
from ..storage.config import ConfigStorage
from ..storage.onepassword import OnepasswordStorage
from ..storage.vault import VaultClient, VaultStorage
from ..yaml import YAMLFoldedString

__all__ = ["SecretsService"]


class SecretsService:
    """Service to manipulate Phalanx secrets.

    Parameters
    ----------
    config_storage
        Storage object for the Phalanx configuration.
    onepassword_storage
        Storage object for 1Password.
    vault_storage
        Storage object for Vault.
    """

    def __init__(
        self,
        config_storage: ConfigStorage,
        onepassword_storage: OnepasswordStorage,
        vault_storage: VaultStorage,
    ) -> None:
        self._config = config_storage
        self._onepassword = onepassword_storage
        self._vault = vault_storage

    def audit(
        self,
        env_name: str,
        static_secrets: StaticSecrets | None = None,
    ) -> str:
        """Compare existing secrets to configuration and report problems.

        Parameters
        ----------
        env_name
            Name of the environment to audit.
        static_secrets
            User-provided static secrets.

        Returns
        -------
        str
            Audit report as a text document.
        """
        environment = self._config.load_environment(env_name)
        if not static_secrets:
            static_secrets = self._get_onepassword_secrets(environment)
        vault_client = self._vault.get_vault_client(environment)

        # Retrieve all the current secrets from Vault and resolve all of the
        # secrets.
        secrets = environment.all_secrets()
        vault_secrets = vault_client.get_environment_secrets()
        resolved = self._resolve_secrets(
            secrets=secrets,
            environment=environment,
            vault_secrets=vault_secrets,
            static_secrets=static_secrets,
        )

        # Compare the resolved secrets to the Vault data.
        missing = []
        mismatch = []
        unknown = []
        for app_name, values in resolved.applications.items():
            for key, secret in values.items():
                if key not in vault_secrets.get(app_name, {}):
                    missing.append(f"{app_name} {key}")
                    continue
                if secret != vault_secrets[app_name][key]:
                    mismatch.append(f"{app_name} {key}")
                del vault_secrets[app_name][key]
        unknown = [f"{a} {k}" for a, lv in vault_secrets.items() for k in lv]

        # Generate the textual report.
        report = ""
        if missing:
            report += "Missing secrets:\n• " + "\n• ".join(missing) + "\n"
        if mismatch:
            report += "Incorrect secrets:\n• " + "\n• ".join(mismatch) + "\n"
        if unknown:
            unknown_str = "\n• ".join(unknown)
            report += "Unknown secrets in Vault:\n• " + unknown_str + "\n"
        return report

    def generate_static_template(self, env_name: str) -> str:
        """Generate a template for providing static secrets.

        The template provides space for all static secrets required for a
        given environment. The resulting file, once the values have been
        added, can be used as input to other secret commands instead of an
        external secret source such as 1Password.

        Parameters
        ----------
        env_name
            Name of the environment.

        Returns
        -------
        dict
            YAML template the user can fill out, as a string.
        """
        environment = self._config.load_environment(env_name)
        template: defaultdict[str, dict[str, StaticSecret]] = defaultdict(dict)
        for application in environment.all_applications():
            for secret in application.all_static_secrets():
                template[secret.application][secret.key] = StaticSecret(
                    description=YAMLFoldedString(secret.description),
                    value=None,
                )
        static_secrets = StaticSecrets(
            applications=template, pull_secret=PullSecret()
        )
        return yaml.dump(static_secrets.dict(by_alias=True), width=70)

    def get_onepassword_static_secrets(self, env_name: str) -> StaticSecrets:
        """Retrieve static secrets for an environment from 1Password.

        Parameters
        ----------
        env_name
            Name of the environment.

        Returns
        -------
        StaticSecrets
            Static secrets for that environment with secret values retrieved
            from 1Password.
        """
        environment = self._config.load_environment(env_name)
        onepassword_secrets = self._get_onepassword_secrets(environment)
        if not onepassword_secrets:
            msg = f"Environment {env_name} not configured to use 1Password"
            raise NoOnepasswordConfigError(msg)
        return onepassword_secrets

    def list_secrets(self, env_name: str) -> list[Secret]:
        """List all required secrets for the given environment.

        Parameters
        ----------
        env_name
            Name of the environment.

        Returns
        -------
        list of Secret
            Secrets required for the given environment.
        """
        environment = self._config.load_environment(env_name)
        return environment.all_secrets()

    def save_vault_secrets(self, env_name: str, path: Path) -> None:
        """Generate JSON files of the Vault secrets for an environment.

        One file per application with secrets will be written to the provided
        path. Each file will be named after the application with ``.json``
        appended, and will contain the secret values for that application.
        Secrets that are required but have no known value will be written as
        null.

        Parameters
        ----------
        env_name
            Name of the environment.
        path
            Output path.
        """
        environment = self._config.load_environment(env_name)
        vault_client = self._vault.get_vault_client(environment)
        vault_secrets = vault_client.get_environment_secrets()
        for app_name, values in vault_secrets.items():
            app_secrets: dict[str, str | None] = {}
            for key, secret in values.items():
                if secret:
                    app_secrets[key] = secret.get_secret_value()
                else:
                    app_secrets[key] = None
            with (path / f"{app_name}.json").open("w") as fh:
                json.dump(app_secrets, fh, indent=2)

    def sync(
        self,
        env_name: str,
        static_secrets: StaticSecrets | None = None,
        *,
        regenerate: bool = False,
        delete: bool = False,
    ) -> None:
        """Synchronize secrets for an environment with Vault.

        Any incorrect secrets will be replaced with the correct value and any
        missing secrets with generate rules will be generated. For generated
        secrets that already have a value in Vault, that value will be kept
        and not replaced.

        Parameters
        ----------
        env_name
            Name of the environment.
        static_secrets
            User-provided static secrets.
        regenerate
            Whether to regenerate any generated secrets.
        delete
            Whether to delete unknown Vault secrets.
        """
        environment = self._config.load_environment(env_name)
        if not static_secrets:
            static_secrets = self._get_onepassword_secrets(environment)
        vault_client = self._vault.get_vault_client(environment)
        secrets = environment.all_secrets()
        vault_secrets = vault_client.get_environment_secrets()

        # Resolve all of the secrets, regenerating if desired.
        resolved = self._resolve_secrets(
            secrets=secrets,
            environment=environment,
            vault_secrets=vault_secrets,
            static_secrets=static_secrets,
            regenerate=regenerate,
        )

        # Replace any Vault secrets that are incorrect.
        self._sync_application_secrets(vault_client, vault_secrets, resolved)
        if resolved.pull_secret and resolved.pull_secret.registries:
            pull_secret = resolved.pull_secret
            self._sync_pull_secret(vault_client, vault_secrets, pull_secret)

        # Optionally delete any unrecognized Vault secrets.
        if delete:
            self._clean_vault_secrets(
                vault_client,
                vault_secrets,
                resolved,
                has_pull_secret=resolved.pull_secret is not None,
            )

    def _clean_vault_secrets(
        self,
        vault_client: VaultClient,
        vault_secrets: dict[str, dict[str, SecretStr]],
        resolved: ResolvedSecrets,
        *,
        has_pull_secret: bool,
    ) -> None:
        """Delete any unrecognized Vault secrets.

        Parameters
        ----------
        vault_client
            Client for talking to Vault for this environment.
        vault_secrets
            Current secrets in Vault for this environment.
        resolved
            Resolved secrets for this environment.
        has_pull_secret
            Whether there should be a pull secret for this environment.
        """
        for application, values in vault_secrets.items():
            if application not in resolved.applications:
                if application == "pull-secret" and has_pull_secret:
                    continue
                print("Deleted Vault secret for", application)
                vault_client.delete_application_secret(application)
                continue
            expected = resolved.applications[application]
            to_delete = set(values.keys()) - set(expected.keys())
            if to_delete:
                for key in to_delete:
                    del values[key]
                vault_client.store_application_secret(application, values)
                for key in sorted(to_delete):
                    print("Deleted Vault secret for", application, key)

    def _get_onepassword_secrets(
        self, environment: Environment
    ) -> StaticSecrets | None:
        """Get static secrets for an environment from 1Password.

        Parameters
        ----------
        environment
            Environment for which to get static secrets.

        Returns
        -------
        dict of StaticSecret or None
            Static secrets for this environment retrieved from 1Password, or
            `None` if this environment doesn't use 1Password.

        Raises
        ------
        NoOnepasswordCredentialsError
            Raised if the environment uses 1Password but no 1Password
            credentials were available in the environment.
        """
        if not environment.onepassword:
            return None
        onepassword = self._onepassword.get_onepassword_client(environment)
        query = {}
        encoded = {}
        for application in environment.all_applications():
            static_secrets = application.all_static_secrets()
            query[application.name] = [s.key for s in static_secrets]
            encoded[application.name] = {
                s.key for s in static_secrets if s.onepassword.encoded
            }
        result = onepassword.get_secrets(query)

        # Fix any secrets that were encoded in base64 in 1Password.
        for app_name, secrets in encoded.items():
            for key in secrets:
                secret = result.applications[app_name][key]
                if secret.value:
                    value = secret.value.get_secret_value().encode()
                    secret.value = SecretStr(b64decode(value).decode())
        return result

    def _resolve_secrets(
        self,
        *,
        secrets: list[Secret],
        environment: Environment,
        vault_secrets: dict[str, dict[str, SecretStr]],
        static_secrets: StaticSecrets | None = None,
        regenerate: bool = False,
    ) -> ResolvedSecrets:
        """Resolve the secrets for a Phalanx environment.

        Resolving secrets is the process where the secret configuration is
        resolved using per-environment Helm chart values to generate the list
        of secrets required for a given environment and their values.

        Parameters
        ----------
        secrets
            Secret configuration by application and key.
        environment
            Phalanx environment for which to resolve secrets.
        vault_secrets
            Current values from Vault. These will be used if compatible with
            the secret definitions.
        static_secrets
            User-provided static secrets.
        regenerate
            Whether to regenerate any generated secrets.

        Returns
        -------
        ResolvedSecrets
            Resolved secrets.

        Raises
        ------
        UnresolvedSecretsError
            Raised if some secrets could not be resolved.
        """
        if not static_secrets:
            static_secrets = StaticSecrets()
        resolved: defaultdict[str, dict[str, SecretStr]] = defaultdict(dict)
        unresolved = list(secrets)
        left = len(unresolved)
        while unresolved:
            secrets = unresolved
            unresolved = []
            for config in secrets:
                app_name = config.application
                vault_values = vault_secrets.get(app_name, {})
                static_values = static_secrets.for_application(app_name)
                static_value = None
                if config.key in static_values:
                    static_value = static_values[config.key].value
                secret = self._resolve_secret(
                    config=config,
                    resolved=resolved,
                    current_value=vault_values.get(config.key),
                    static_value=static_value,
                    regenerate=regenerate,
                )
                if secret:
                    resolved[config.application][config.key] = secret
                else:
                    unresolved.append(config)
            if len(unresolved) >= left:
                raise UnresolvedSecretsError(unresolved)
            left = len(unresolved)
        return ResolvedSecrets(
            applications=resolved, pull_secret=static_secrets.pull_secret
        )

    def _resolve_secret(
        self,
        *,
        config: Secret,
        resolved: dict[str, dict[str, SecretStr]],
        current_value: SecretStr | None,
        static_value: SecretStr | None,
        regenerate: bool = False,
    ) -> SecretStr | None:
        """Resolve a single secret.

        Parameters
        ----------
        config
            Configuration of the secret.
        resolved
            Other secrets for that environment that have already been
            resolved.
        current_value
            Current secret value in Vault, if known.
        static_value
            User-provided static secret value, if any.
        regenerate
            Whether to regenerate any generated secrets.

        Returns
        -------
        SecretStr or None
            Resolved value of the secret, or `None` if the secret cannot yet
            be resolved (because, for example, the secret from which it is
            copied has not yet been resolved).
        """
        value = None

        # See if the value comes from configuration, either hard-coded or via
        # copy or generate rules. If not, it must be a static secret, in which
        # case use the value from a static secret source, if available. If
        # none is available from a static secret source but we have a current
        # value, use that. Only fail if there is no static secret source and
        # no current value.
        if config.value:
            value = config.value
        elif config.copy_rules:
            application = config.copy_rules.application
            other = resolved.get(application, {}).get(config.copy_rules.key)
            if not other:
                return None
            value = other
        elif config.generate:
            if current_value and not regenerate:
                value = current_value
            elif isinstance(config.generate, SourceSecretGenerateRules):
                other_key = config.generate.source
                other = resolved.get(config.application, {}).get(other_key)
                if not other:
                    return None
                value = config.generate.generate(other)
            else:
                value = config.generate.generate()
        else:
            value = static_value or current_value

        # Return the resolved secret.
        return value

    def _sync_application_secrets(
        self,
        vault_client: VaultClient,
        vault_secrets: dict[str, dict[str, SecretStr]],
        resolved: ResolvedSecrets,
    ) -> None:
        """Sync the application secrets for an environment to Vault.

        Changes made to Vault will be reported to standard output. This will
        not delete any stray secrets in Vault, only add any missing ones.

        Parameters
        ----------
        vault_client
            Client for talking to Vault for this environment.
        vault_secrets
            Current secrets in Vault for this environment.
        resolved
            Resolved secrets for this environment.
        """
        for application, values in resolved.applications.items():
            if application not in vault_secrets:
                vault_client.store_application_secret(application, values)
                print("Created Vault secret for", application)
                continue
            vault_app_secrets = vault_secrets[application]
            for key, secret in values.items():
                if secret != vault_app_secrets.get(key):
                    vault_client.update_application_secret(
                        application, key, secret
                    )
                    print("Updated Vault secret for", application, key)

    def _sync_pull_secret(
        self,
        vault_client: VaultClient,
        vault_secrets: dict[str, dict[str, SecretStr]],
        pull_secret: PullSecret,
    ) -> None:
        """Sync the pull secret for an environment to Vault.

        Parameters
        ----------
        vault_client
            Client for talking to Vault for this environment.
        vault_secrets
            Current secrets in Vault for this environment.
        pull_secret
            Pull secret for the environment.
        """
        value = SecretStr(pull_secret.to_dockerconfigjson())
        secret = {".dockerconfigjson": value}
        if "pull-secret" not in vault_secrets:
            vault_client.store_application_secret("pull-secret", secret)
            print("Created Vault secret for pull-secret")
        elif secret != vault_secrets["pull-secret"]:
            vault_client.store_application_secret("pull-secret", secret)
            print("Updated Vault secret for pull-secret")
