import io

import pytest

from tentaclio import urls
from tentaclio.credentials import TentaclioFileError, injection, reader


@pytest.fixture
def empty_creds_yaml():
    return ""


@pytest.fixture
def creds_yaml_not_key_value_mapping():
    return """
- 1
- 2
"""


@pytest.fixture
def no_secrets_block_yaml():
    return """
example: {}
"""


@pytest.fixture
def creds_yaml():
    return """
secrets:
    local_ftp: ftp://user:password@local.com
    remote_db: postgresql://user_db:password_db@db.com/database
"""


@pytest.fixture
def creds_yaml_empty_secrets():
    return """
secrets:
"""


@pytest.fixture
def creds_yaml_secrets_bad_indentation():
    return """
secrets:
local_ftp: ftp://user:password@local.com
"""


@pytest.fixture
def creds_yaml_secrets_not_key_value_mapping():
    return """
secrets:
    - 1
    - 2
"""


@pytest.fixture
def creds_yaml_bad_url():
    return """
secrets:
    local_ftp: ftp://user:password@local.com
    remote_db: I'm @not a V&?!lid url
"""


@pytest.fixture
def creds_yaml_env_variables():
    return """
secrets:
    local_ftp: ftp://${USER}:${PASSWORD}@local.com
    remote_db: postgresql://${USER_DB}:${PASSWORD_DB}@db.com/database
"""


@pytest.fixture
def creds_yaml_bad_env_variables():
    return """
secrets:
    local_ftp: ftp://${FAKE_USER}:${FAKE_PASSWORD}@local.com
    remote_db: postgresql://${FAKE_USER_DB}:${FAKE_PASSWORD_DB}@db.com/database
"""


def test_bad_yaml():
    with pytest.raises(TentaclioFileError, match="Your tentaclio secrets file is malformed"):
        data = io.StringIO("  a: b\nc: d")
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_empty_credentials_file(empty_creds_yaml):
    with pytest.raises(TentaclioFileError, match="The YAML secrets file is empty"):
        data = io.StringIO(empty_creds_yaml)
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_credentials_file_not_key_value_mapping(creds_yaml_not_key_value_mapping):
    with pytest.raises(
        TentaclioFileError,
        match="The YAML secrets file must be a mapping of key-value pairs",
    ):
        data = io.StringIO(creds_yaml_not_key_value_mapping)
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_credentials_no_secrets_block(no_secrets_block_yaml):
    with pytest.raises(TentaclioFileError, match="No `secrets:` key found in YAML secrets file"):
        data = io.StringIO(no_secrets_block_yaml)
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_credentials_empty_secrets(creds_yaml_empty_secrets):
    data = io.StringIO(creds_yaml_empty_secrets)
    with pytest.raises(TentaclioFileError, match="No entries found within the `secrets:` block"):
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_credentials_secrets_bad_indentation(creds_yaml_secrets_bad_indentation):
    data = io.StringIO(creds_yaml_secrets_bad_indentation)
    with pytest.raises(TentaclioFileError, match="Are the entries indented correctly"):
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_credentials_secrets_not_key_value_mapping(creds_yaml_secrets_not_key_value_mapping):
    data = io.StringIO(creds_yaml_secrets_not_key_value_mapping)
    with pytest.raises(
        TentaclioFileError,
        match=(
            r"The value returned by `yaml.safe_load\(\)` for the `secrets:` block was not a "
            r"Python `dict`"
        ),
    ):
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("ftp://local.com/file.txt", "ftp://user:password@local.com/file.txt"),
        ("postgresql://db.com/database", "postgresql://user_db:password_db@db.com/database"),
    ],
)
def test_credentials(url, expected, creds_yaml):
    data = io.StringIO(creds_yaml)
    injector = reader.add_credentials_from_reader(injection.CredentialsInjector(), data)

    result = injector.inject(urls.URL(url))
    assert result == urls.URL(expected)


def test_credentials_bad_url(creds_yaml_bad_url):
    data = io.StringIO(creds_yaml_bad_url)
    with pytest.raises(Exception):
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("ftp://local.com/file.txt", "ftp://user:password@local.com/file.txt"),
        ("postgresql://db.com/database", "postgresql://user_db:password_db@db.com/database"),
    ],
)
def test_credentials_env_variable(url, expected, creds_yaml_env_variables, monkeypatch):
    monkeypatch.setenv("USER", "user")
    monkeypatch.setenv("USER_DB", "user_db")
    monkeypatch.setenv("PASSWORD", "password")
    monkeypatch.setenv("PASSWORD_DB", "password_db")

    data = io.StringIO(creds_yaml_env_variables)
    injector = reader.add_credentials_from_reader(injection.CredentialsInjector(), data)

    result = injector.inject(urls.URL(url))
    assert result == urls.URL(expected)


def test_credentials_bad_env_variable(creds_yaml_bad_env_variables):
    data = io.StringIO(creds_yaml_bad_env_variables)
    with pytest.raises(EnvironmentError):
        reader.add_credentials_from_reader(injection.CredentialsInjector(), data)


def test_load_from_file_expands_user_path(tmp_path, monkeypatch, creds_yaml):
    """A leading ~ in the secrets path resolves to the user's home."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "secrets.yaml").write_text(creds_yaml)

    injector = reader._load_from_file(injection.CredentialsInjector(), "~/secrets.yaml")

    result = injector.inject(urls.URL("ftp://local.com/file.txt"))
    assert result == urls.URL("ftp://user:password@local.com/file.txt")
