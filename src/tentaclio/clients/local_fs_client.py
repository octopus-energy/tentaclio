"""Local filesystem client."""

import os
from typing import Iterable, Union

from tentaclio import fs, protocols, urls

from . import base_client

__all__ = ["LocalFSClient"]


class LocalFSClient(base_client.BaseClient["LocalFSClient"]):
    """Local filesystem client implementation."""

    allowed_schemes = ["", "file"]

    path: str

    def __init__(self, url: Union[urls.URL, str]) -> None:
        """Create a new LocalFS client."""
        super().__init__(url)

        self.path = os.path.expanduser(self.url.path)

    def _connect(self) -> "LocalFSClient":
        return self

    def close(self) -> None:
        """Close the dummy connection to the local fs."""
        self.closed = True

    # Stream methods:

    def get(self, writer: protocols.ByteWriter, **kwargs) -> None:
        """Get the contents of the file."""
        with open(self.path, "rb") as f:
            writer.write(f.read())

    def put(self, reader: protocols.ByteReader, **kwargs) -> None:
        """Write the contents of the reader to the file."""
        self.makedirs(os.path.dirname(self.path))
        with open(self.path, "wb") as f:
            f.write(bytes(reader.read()))

    def makedirs(self, directory: str, mode: int = 0o777) -> None:
        """Create parent directories, preserving existing directories."""
        if directory:
            os.makedirs(directory, mode=mode, exist_ok=True)

    # scandir related methods

    def scandir(self, **kwargs) -> Iterable[fs.DirEntry]:
        """Scan the connection url to create dir entries."""
        os_dir_entries = os.scandir(self.path)
        return map(_from_os_dir_entry, os_dir_entries)

    # remove

    def remove(self):
        """Remove the file from the local file system."""
        os.remove(self.path)


def _from_os_dir_entry(original: os.DirEntry) -> fs.DirEntry:
    return fs.DirEntry(
        url=urls.URL("file://" + os.path.abspath(original.path)),
        is_dir=bool(original.is_dir()),
        is_file=bool(original.is_file()),
    )
