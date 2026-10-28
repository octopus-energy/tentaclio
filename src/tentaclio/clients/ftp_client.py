"""FTP ans SFTP stream clients."""

import ftplib
import io
import logging
import os
import stat
from typing import Iterable, Optional, Union

from paramiko import DSSKey, ECDSAKey, Ed25519Key, PKey, RSAKey, sftp_client
from paramiko.transport import Transport

from tentaclio import fs, protocols, urls

from . import base_client, decorators, exceptions

logger = logging.getLogger(__name__)

__all__ = ["FTPClient", "SFTPClient"]


class FTPClient(base_client.BaseClient["FTPClient"]):
    """Generic FTP client."""

    allowed_schemes = ["ftp"]

    conn: ftplib.FTP

    def __init__(self, url: Union[str, urls.URL], **kwargs) -> None:
        """Create a new ftp client based on the url starting with ftp://."""
        super().__init__(url)
        self.port = self.url.port or 21

    # Connection methods:

    def _connect(self) -> ftplib.FTP:
        logging.info(f"starting ftp connection to {self.url}")
        conn = ftplib.FTP()
        conn.connect(self.url.hostname or "", port=self.port)
        conn.login(user=self.url.username or "", passwd=self.url.password or "")
        return conn

    # Stream methods:

    @decorators.check_conn
    def get(self, writer: protocols.ByteWriter, file_path: Optional[str] = None) -> None:
        """Write the contents of a remote file into the passed writer.

        Arguments:
            :file_path: The path of the remote file if not passed
                in the constructor as part of the url.
        """
        remote_path = file_path or self.url.path
        if remote_path == "":
            raise exceptions.FTPError("Missing remote file path")

        try:
            self.conn.retrbinary(f"RETR {remote_path}", writer.write)
        except Exception as e:
            raise exceptions.FTPError("Error from ftp server:" + str(e))

    @decorators.check_conn
    def put(self, reader: protocols.ByteReader, file_path: Optional[str] = None) -> None:
        """Write the contents of the reader into the remote file.

        Arguments:
            :file_path: The path of the remote file if not passed
                in the constructor as part of the url.
        """
        remote_path = file_path or self.url.path
        self.makedirs(os.path.dirname(remote_path))
        # storbinary only works with io.BytesIO
        buff = io.BytesIO(bytearray(reader.read()))
        self.conn.storbinary(f"STOR {remote_path}", buff)

    @decorators.check_conn
    def makedirs(self, remotedir: str) -> None:
        """Create missing FTP directories without changing the working directory."""
        if not remotedir or remotedir == "/":
            return
        parent = os.path.dirname(remotedir.rstrip("/"))
        if parent and parent != remotedir:
            self.makedirs(parent)
        try:
            self.conn.mkd(remotedir)
        except ftplib.error_perm:
            # Only ignore an existing directory, not a permission failure.
            original = self.conn.pwd()
            try:
                self.conn.cwd(remotedir)
            finally:
                self.conn.cwd(original)

    # Helpers:

    def _scan_mlds(self, base_url):
        entries = []
        for mlsd_entry in self.conn.mlsd(self.url.path, facts=["type"]):
            # https://docs.python.org/3/library/ftplib.html#ftplib.FTP.mlsd
            file_name = mlsd_entry[0]
            entry_type = mlsd_entry[1]["type"]

            url = urls.URL(base_url + file_name)
            if entry_type == "dir":
                entries.append(fs.build_folder_entry(url))
            else:
                entries.append(fs.build_file_entry(url))

        return entries

    def _scan_dir(self, base_url):
        """Fallback if no mlst is implemented in the server.

        Do not really hope this will work everywhere.
        """
        entries = []

        def parser(line):
            nonlocal entries  # noqa
            parts = line.split()
            file_name = parts[-1]
            url = urls.URL(base_url + file_name)
            if parts[0][0] == "d":
                # first line would look drwxrwx---
                # if it's  dir
                entries.append(fs.build_folder_entry(url))
            else:
                entries.append(fs.build_file_entry(url))

        self.conn.dir(self.url.path.lstrip("/"), parser)

        return entries

    def scandir(self, **kwargs) -> Iterable[fs.DirEntry]:
        """Scan the connection url to create dir entries."""
        base_url = f"ftp://{self.url.hostname}:{self.port}{self.url.path.rstrip('/')}/"
        try:
            return self._scan_mlds(base_url)
        except ftplib.error_perm as e:
            if "501 'MLST type;'" in str(e):
                # if mlst is not implemented in the server
                # try to use dir and parse the output
                return self._scan_dir(base_url)
            else:
                raise exceptions.FTPError("Error from ftp server:" + str(e))

    @decorators.check_conn
    def remove(self):
        """Remove the file from the ftp."""
        self.conn.delete(self.url.path)


class SFTPClient(base_client.BaseClient["SFTPClient"]):
    """SFTP stream client."""

    allowed_schemes = ["sftp"]

    conn: sftp_client.SFTPClient
    username: str
    password: str
    port: int
    private_key: str
    private_key_pass: str

    def __init__(
        self,
        url: Union[str, urls.URL],
        private_key_path: Optional[str] = None,
        private_key_password: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Create a new sftp client based on the url starting with sftp://."""
        super().__init__(url)
        self.username = self.url.username or ""
        self.password = self.url.password or ""
        self.port = self.url.port or 22
        self.private_key_path = private_key_path or (
            self.url.query.get("private_key_path") if self.url.query else None
        )
        self.private_key_password = private_key_password or (
            self.url.query.get("private_key_password") if self.url.query else None
        )

    def _get_private_key(self) -> PKey:
        if not self.private_key_path:
            raise exceptions.FTPError("No private key path provided.")

        with open(self.private_key_path, "r", encoding="utf-8") as head:
            key_id = head.readline()[11:][:-18]

        key_types = {"DSA": DSSKey, "EC": ECDSAKey, "OPENSSH": Ed25519Key, "RSA": RSAKey}
        key = key_types[key_id.strip()]  # type: type[PKey]
        private_key = key.from_private_key_file(self.private_key_path, self.private_key_password)
        return private_key

    def _authenticate(self, transport: Transport) -> None:
        if self.private_key_path:
            private_key = self._get_private_key()
            transport.auth_publickey(self.username, private_key)
        elif self.password:
            transport.auth_password(self.username, self.password)
        else:
            raise exceptions.FTPError("No password or private key provided.")
        if not transport.is_authenticated():
            raise exceptions.FTPError("Authentication failed.")

    # Connection methods:

    def _connect(self) -> sftp_client.SFTPClient:
        if self.url.hostname is None:
            raise exceptions.FTPError("Missing hostname in url")
        transport = Transport((self.url.hostname, self.port))
        transport.start_client()
        self._authenticate(transport)

        client = sftp_client.SFTPClient.from_transport(transport)
        if not client:
            raise exceptions.FTPError("Unable to connect to the server")
        else:
            return client

    # Stream methods:

    @decorators.check_conn
    def get(self, writer: protocols.ByteWriter, file_path: Optional[str] = None) -> None:
        """Write the contents of a remote file into the passed writer.

        Arguments:
            :file_path: The path of the remote file if not passed
                in the constructor as part of the url.
        """
        remote_path = file_path or self.url.path
        if remote_path == "":
            raise exceptions.FTPError("Missing remote file path")

        if not self.isfile(remote_path):
            raise exceptions.FTPError("Unable to fetch the remote file")

        logger.info(f"sftp reading from {remote_path}")

        if not isinstance(writer, io.BytesIO):
            raise exceptions.FTPError("Writer is not a BytesIO object")
        else:
            self.conn.getfo(remote_path, writer)

    @decorators.check_conn
    def put(self, reader: protocols.ByteReader, file_path: Optional[str] = None) -> None:
        """Write the contents of the reader into the remote file.

        Arguments:
            :file_path: The path of the remote file if not passed
                in the constructor as part of the url.
        """
        remote_path = file_path or self.url.path
        if remote_path == "":
            raise exceptions.FTPError("Missing remote file path")

        logger.info(f"sftp writing to {remote_path}")
        self.makedirs(os.path.dirname(remote_path))
        # this gives permission error
        # self.conn.putfo(remote_path, file_obj.read())
        # but open works
        with self.conn.open(remote_path, mode="wb") as f:
            f.write(reader.read())

    def scandir(self, **kwargs) -> Iterable[fs.DirEntry]:
        """Scan the connection url to create dir entries."""
        base_url = f"sftp://{self.url.hostname}:{self.port}{self.url.path}/"
        entries = []
        for attrs in self.conn.listdir_attr(self.url.path):
            if attrs.st_mode is None:
                continue
            url = urls.URL(base_url + attrs.filename)
            if stat.S_ISDIR(attrs.st_mode):
                entries.append(fs.build_folder_entry(url))

            elif stat.S_ISREG(attrs.st_mode):
                entries.append(fs.build_file_entry(url))
            else:
                continue  # ignore other type of entries
        return entries

    def isdir(self, remotedir: str) -> bool:
        """Return True if remotedir is a directory, False otherwise."""
        try:
            stat_mode = self.conn.stat(remotedir).st_mode
            if isinstance(stat_mode, int):
                return stat.S_ISDIR(stat_mode)
            return False
        except IOError:
            # file does not exist
            return False

    def isfile(self, remotepath: str) -> bool:
        """Return True if remotepath is a file, False otherwise."""
        try:
            stat_mode = self.conn.stat(remotepath).st_mode
            if isinstance(stat_mode, int):
                return stat.S_ISREG(stat_mode)
            return False
        except IOError:
            # file does not exist
            return False

    def makedirs(self, remotedir: str, mode: int = 777) -> None:
        """Create all directories in remotedir as needed, setting their mode to mode if created."""
        if not remotedir or remotedir == "/":
            return
        if self.isdir(remotedir):
            return
        elif self.isfile(remotedir):
            raise OSError(
                "a file with the same name as the remotedir, " "'%s', already exists." % remotedir
            )
        else:
            head, tail = os.path.split(remotedir)
            if head and not self.isdir(head):
                self.makedirs(head, mode)

            if tail:
                self.conn.mkdir(remotedir, mode=int(str(mode), 8))

    @decorators.check_conn
    def remove(self):
        """Remove the file from the ftp."""
        self.conn.remove(self.url.path)
