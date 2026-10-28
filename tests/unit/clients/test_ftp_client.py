import collections
import ftplib
import io
import stat

import pytest

from tentaclio import URL
from tentaclio.clients import exceptions, ftp_client


@pytest.fixture()
def mocked_ftp_conn(mocker):
    with mocker.patch.object(ftp_client.FTPClient, "_connect", return_value=mocker.MagicMock()):
        yield


@pytest.fixture()
def mocked_sftp_conn(mocker):
    with mocker.patch.object(ftp_client.SFTPClient, "_connect", return_value=mocker.MagicMock()):
        yield


class TestFTPClient:
    @pytest.mark.parametrize("url", ["file:///test.file", "sftp://:@localhost", "s3://:@s3"])
    def test_invalid_scheme(self, url):
        with pytest.raises(ValueError):
            ftp_client.FTPClient(url)

    @pytest.mark.parametrize(
        "url,username,password,hostname,port,path",
        [
            ("ftp://:@localhost", "", "", "localhost", None, ""),
            ("ftp://login:pass@localhost", "login", "pass", "localhost", None, ""),
            ("ftp://:@localhost:21", "", "", "localhost", 21, ""),
            ("ftp://:@localhost:21/path", "", "", "localhost", 21, "/path"),
        ],
    )
    def test_parsing_ftp_url(self, url, username, password, hostname, port, path):
        parsed_url = ftp_client.FTPClient(url).url

        assert parsed_url.scheme == "ftp"
        assert parsed_url.hostname == hostname
        assert parsed_url.username == username
        assert parsed_url.password == password
        assert parsed_url.port == port
        assert parsed_url.path == path

    @pytest.mark.parametrize("url,path", [("ftp://:@localhost", None)])
    def test_get_invalid_path(self, url, path, mocked_ftp_conn):
        with ftp_client.FTPClient(url) as client:
            with pytest.raises(exceptions.FTPError):
                client.get(io.StringIO(), file_path=path)

    def test_get(self, mocked_ftp_conn):
        expected = bytes("hello", "utf-8")

        client = ftp_client.FTPClient("ftp://user:pass@localhost/myfile.txt")
        client.connect().retrbinary = lambda _, f: f(expected)  # type: ignore[attr-defined]
        buff = io.BytesIO()
        with client:
            client.get(buff)

        assert buff.getvalue() == expected

    def test_put(self, mocked_ftp_conn):
        expected = bytes("hello", "utf-8")
        result = io.BytesIO()

        client = ftp_client.FTPClient("ftp://user:pass@localhost/myfile.txt")
        conn = client.connect()
        conn.storbinary = lambda _, f: result.write(f.read())  # type: ignore[attr-defined]

        with client:
            reader = io.BytesIO(expected)
            client.put(reader)
        result.seek(0)

        assert result.getvalue() == expected

    def test_scandir_file(self, mocked_ftp_conn):
        fake_entries = [("my_file.txt", {"type": "file"})]
        client = ftp_client.FTPClient("ftp://localhost:9999/mydir")
        with client:
            client.conn.mlsd.return_value = fake_entries  # type: ignore[attr-defined]

        entries = list(client.scandir())
        assert entries[0].url == URL("ftp://localhost:9999/mydir/my_file.txt")
        assert entries[0].is_file

    def test_scandir_folder(self, mocked_ftp_conn):
        fake_entries = [("another_dir", {"type": "dir"})]
        client = ftp_client.FTPClient("ftp://localhost:9999/mydir")
        with client:
            client.conn.mlsd.return_value = fake_entries  # type: ignore[attr-defined]

        entries = list(client.scandir())
        assert entries[0].url == URL("ftp://localhost:9999/mydir/another_dir")
        assert entries[0].is_dir

    def test_scandir_mlst_not_supported(self, mocked_ftp_conn):
        client = ftp_client.FTPClient("ftp://localhost:9999/mydir")
        with client:
            client.conn.mlsd.side_effect = ftplib.error_perm(  # type: ignore[attr-defined]
                "501 'MLST type;'"
            )

        client.scandir()
        # assert we do a simple dir in the client
        client.conn.dir.assert_called()  # type: ignore[attr-defined]

    def test_scandir_mlst_propagate_error(self, mocked_ftp_conn):
        client = ftp_client.FTPClient("ftp://localhost:9999/mydir")
        with client:
            client.conn.mlsd.side_effect = Exception(  # type: ignore[attr-defined]
                "any other exception"
            )

        with pytest.raises(Exception, match="any other exception"):
            client.scandir()

    def test_scandir_dir_file(self, mocked_ftp_conn):
        fake_entry = "-rwxrwxrwx   1 owner    group               0 Feb 17 17:54 important_file"
        client = ftp_client.FTPClient("ftp://localhost:9999/mydir")
        with client:
            client.conn.mlsd.side_effect = ftplib.error_perm(  # type: ignore[attr-defined]
                "501 'MLST type;'"
            )
            # mock ftplib.dir behaviour
            client.conn.dir = (  # type: ignore[method-assign]
                lambda url, parser: parser(fake_entry)  # type: ignore[assignment,misc]
            )

        entries = list(client.scandir())
        assert entries[0].url == URL("ftp://localhost:9999/mydir/important_file")
        assert not entries[0].is_dir

    def test_scandir_dir_folder(self, mocked_ftp_conn):
        fake_entry = "drwxrwxrwx   1 owner    group               0 Feb 17 17:54 nested"
        client = ftp_client.FTPClient("ftp://localhost:9999/mydir")
        with client:
            client.conn.mlsd.side_effect = ftplib.error_perm(  # type: ignore[attr-defined]
                "501 'MLST type;'"
            )
            # mock ftplib.dir behaviour
            client.conn.dir = (  # type: ignore[method-assign]
                lambda url, parser: parser(fake_entry)  # type: ignore[assignment,misc]
            )

        entries = list(client.scandir())
        assert entries[0].url == URL("ftp://localhost:9999/mydir/nested")
        assert entries[0].is_dir


class TestSFTPClient:
    @pytest.mark.parametrize("url", ["file:///test.file", "ftp://:@localhost", "s3://:@s3"])
    def test_invalid_scheme(self, url):
        with pytest.raises(ValueError):
            ftp_client.SFTPClient(url)

    @pytest.mark.parametrize("url,path", [("sftp://:@localhost", None)])
    def test_get_invalid_path(self, url, path, mocked_sftp_conn):
        with ftp_client.SFTPClient(url) as client:
            with pytest.raises(exceptions.FTPError):
                client.get(io.StringIO(), file_path=path)

    def test_get(self, mocked_sftp_conn):
        expected = bytes("hello", "utf-8")
        FakeAttr = collections.namedtuple("FakeAttr", ["st_mode"])
        client = ftp_client.SFTPClient("sftp://user:pass@localhost/myfile.txt")
        conn = client.connect()
        conn.getfo = lambda _, f: f.write(expected)  # type: ignore[attr-defined]
        buff = io.BytesIO()
        with client:
            client.conn.stat.return_value = FakeAttr(stat.S_IFREG)  # type: ignore[attr-defined]
            client.get(buff)

        assert buff.getvalue() == expected

    def test_put(self, mocked_sftp_conn):
        expected = bytes("hello", "utf-8")
        result = io.BytesIO()

        client = ftp_client.SFTPClient("sftp://user:pass@localhost/myfile.txt")
        # forgive me father for I have sinned.
        # mocking the context manager of the connection, a bit coupled with the
        # actual implementation and long.
        conn = client.connect()
        handle = conn.open().__enter__()  # type: ignore[attr-defined]
        handle.write = lambda data: result.write(data)

        with client:
            reader = io.BytesIO(expected)
            client.put(reader)
        result.seek(0)

        assert result.getvalue() == expected

    @pytest.mark.parametrize(
        ["url", "port"],
        [
            ("sftp://user:pass@localhost/myfile.txt", 22),
            ("sftp://user:pass@localhost:200/myfile.txt", 200),
        ],
    )
    def test_set_default_port(self, url, port, mocked_sftp_conn):
        client = ftp_client.SFTPClient(url)
        assert client.port == port

    def test_scandir_file(self, mocked_sftp_conn):
        FakeAttr = collections.namedtuple("FakeAttr", ["filename", "st_mode"])
        client = ftp_client.SFTPClient("sftp://localhost:9999/mydir")
        with client:
            client.conn.listdir_attr.return_value = [  # type: ignore[attr-defined]
                FakeAttr("my_file.txt", stat.S_IFREG)
            ]

        entries = list(client.scandir())
        print("entries", entries)
        assert entries[0].url == URL("sftp://localhost:9999/mydir/my_file.txt")
        assert entries[0].is_file

    def test_scandir_folder(self, mocked_sftp_conn):
        FakeAttr = collections.namedtuple("FakeAttr", ["filename", "st_mode"])
        client = ftp_client.SFTPClient("sftp://localhost:9999/mydir")
        with client:
            client.conn.listdir_attr.return_value = [  # type: ignore[attr-defined]
                FakeAttr("other_folder", stat.S_IFDIR)
            ]

        entries = list(client.scandir())
        print("entries", entries)
        assert entries[0].url == URL("sftp://localhost:9999/mydir/other_folder")
        assert entries[0].is_dir


def test_ftp_write_creates_parent_directories(mocked_ftp_conn, mocker):
    client = ftp_client.FTPClient("ftp://user:pass@localhost/new/deep/data.txt")
    with client:
        mkdir = mocker.patch.object(client.conn, "mkd")
        store = mocker.patch.object(client.conn, "storbinary")
        client.put(io.BytesIO(b"data"))
        assert [call.args[0] for call in mkdir.call_args_list] == ["/new", "/new/deep"]
        store.assert_called_once()


def test_sftp_write_creates_parent_directories(mocked_sftp_conn, mocker):
    client = ftp_client.SFTPClient("sftp://user:pass@localhost/new/deep/data.txt")
    with client:
        mocker.patch.object(client.conn, "stat", side_effect=IOError("not found"))
        mkdir = mocker.patch.object(client.conn, "mkdir")
        client.put(io.BytesIO(b"data"))
        assert [call.args[0] for call in mkdir.call_args_list] == ["/new", "/new/deep"]


def test_ftp_makedirs_existing_directory(mocked_ftp_conn, mocker):
    client = ftp_client.FTPClient("ftp://user:pass@localhost/new/data.txt")
    with client:
        mocker.patch.object(client.conn, "mkd", side_effect=ftplib.error_perm("exists"))
        cwd = mocker.patch.object(client.conn, "cwd")
        mocker.patch.object(client.conn, "pwd", return_value="/")
        client.makedirs("/new")
        assert [call.args[0] for call in cwd.call_args_list] == ["/new", "/"]


def test_ftp_makedirs_rejects_permission_error(mocked_ftp_conn, mocker):
    client = ftp_client.FTPClient("ftp://user:pass@localhost/new/data.txt")
    with client:
        mocker.patch.object(client.conn, "mkd", side_effect=ftplib.error_perm("permission denied"))
        mocker.patch.object(client.conn, "cwd", side_effect=ftplib.error_perm("permission denied"))
        mocker.patch.object(client.conn, "pwd", return_value="/")
        with pytest.raises(ftplib.error_perm):
            client.makedirs("/new")
