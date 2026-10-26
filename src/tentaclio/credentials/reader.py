"""Read credentials from yaml file."""

import io
import logging
import os
import re

import yaml

from tentaclio import protocols, urls
from tentaclio.credentials import injection


logger = logging.getLogger(__name__)

SECRETS = "secrets"
TENTACLIO_SECRETS_FILE = "TENTACLIO__SECRETS_FILE"
ENV_VARIABLE_PATTERN = re.compile(r"\${[a-zA-Z_]+[a-zA-Z0-9_]*}")
NOT_VALID_ENV_VARIABLE_VALUES = "[${}]"


class TentaclioFileError(Exception):
    """Tentaclio secrets file errors."""

    TENTACLIO_FILE = os.getenv(TENTACLIO_SECRETS_FILE, "<unknown file>")
    ERROR_TEMPLATE = """
#########################################

Your tentaclio secrets file is malformed:

File: {tentaclio_file}

{message}

Check https://github.com/octopus-energy/tentaclio#credentials-file for more info about this file
"""

    def __init__(self, message: str):
        """Intialise a new TentaclioFileError."""
        message = self.ERROR_TEMPLATE.format(message=message, tentaclio_file=self.TENTACLIO_FILE)
        super().__init__(message)


def add_credentials_from_env_file(
    injector: injection.CredentialsInjector,
) -> injection.CredentialsInjector:
    """Add credentials from a configurable yaml file.

    The path of this file is expected to be set in the environment as
    `TENTACLIO__SECRETS_FILE`
    """
    secrets_file = os.getenv(TENTACLIO_SECRETS_FILE, "")
    if secrets_file != "":
        injector = _load_from_file(injector, secrets_file)
    return injector


def _process_mark_error(error: yaml.MarkedYAMLError) -> str:
    error_str = ""
    if error.problem_mark is not None:
        error_str += str(error.problem) + "\n"
        error_str += str(error.problem_mark) + "\n"
    if error.context_mark is not None:
        error_str += str(error.context) + "\n"
        error_str += str(error.context_mark) + "\n"
    return error_str


def _load_creds_from_yaml(yaml_reader: protocols.Reader) -> dict:
    try:
        loaded_data = yaml.safe_load(io.StringIO(yaml_reader.read()))
    except yaml.MarkedYAMLError as error:
        raise TentaclioFileError(_process_mark_error(error))

    if loaded_data is None:
        raise TentaclioFileError(
            f"The YAML secrets file is empty. It must contain a top-level `{SECRETS}:` key."
        )
    if not isinstance(loaded_data, dict):
        raise TentaclioFileError(
            "The YAML secrets file must be a mapping of key-value pairs like:\n"
            f"    {SECRETS}:\n"
            "        my_creds_name: http://user:password@google.com/path\n"
            "        my_db: postgresql://user_db:password@octopus.energy/database\n"
            "The value returned by `yaml.safe_load()` was not a Python `dict`."
        )
    if SECRETS not in loaded_data:
        raise TentaclioFileError(
            f"No `{SECRETS}:` key found in YAML secrets file. Make sure the file has a "
            f"`{SECRETS}:` element."
        )

    secrets = loaded_data[SECRETS]

    if secrets is None:
        raise TentaclioFileError(
            f"No entries found within the `{SECRETS}:` block of the YAML secrets file.\n"
            f"Are the entries indented correctly or is the `{SECRETS}:` block empty?"
        )
    if not isinstance(secrets, dict):
        raise TentaclioFileError(
            f"The `{SECRETS}:` block of the YAML secrets file must be a mapping of key-value "
            "pairs like:\n"
            f"    {SECRETS}:\n"
            "        my_creds_name: http://user:password@google.com/path\n"
            "        my_db: postgresql://user_db:password@octopus.energy/database\n"
            f"The value returned by `yaml.safe_load()` for the `{SECRETS}:` block was not a "
            "Python `dict`."
        )

    return secrets


def _load_from_file(
    injector: injection.CredentialsInjector, path: str
) -> injection.CredentialsInjector:
    # Expand a leading ~ so a path like ~/secrets.yaml resolves to the user's
    # home directory rather than a literal "~" entry in the working directory.
    path = os.path.expanduser(path)
    try:
        with open(path, "r") as f:
            return add_credentials_from_reader(injector, f)
    except IOError as e:
        raise TentaclioFileError("File not found") from e


def _replace_env_variables(url: str) -> str:
    """Replace the environment variables inside the url by its value in the environment.

    Environment variables match the following format: ${ENV_VARIABLE_NAME}
    """
    env_variables = re.findall(ENV_VARIABLE_PATTERN, url)
    for env_variable in env_variables:
        env_variable_name = re.sub(NOT_VALID_ENV_VARIABLE_VALUES, "", env_variable)
        env_value = os.getenv(env_variable_name)
        if not env_value:
            raise EnvironmentError(
                f"Error while reading variable '{env_variable_name}' from the environment "
                f"when interpolating it from the secrets file. "
                f"Check that the variable exists in your environment."
            )
        url = url.replace(env_variable, env_value)
    return url


def add_credentials_from_reader(
    injector: injection.CredentialsInjector, yaml_reader: protocols.Reader
) -> injection.CredentialsInjector:
    """Read the credentials from a yml.

    The file has the following format:
        secrets:
            my_creds_name: http://user:password@google.com/path
            my_db: postgresql://user_db:password@octopus.energy/database

    """
    creds = _load_creds_from_yaml(yaml_reader)
    for name, url in creds.items():
        logger.info(f"Adding secret: {name}")
        url = _replace_env_variables(url)
        try:
            injector.register_credentials(urls.URL(url))
        except Exception as e:
            logger.error(f"Error while registering credentials {name}:{url} from file")
            raise e

    return injector
