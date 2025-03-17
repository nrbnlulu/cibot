from dataclasses import dataclass
import subprocess
from abc import ABC, abstractmethod

from msgspec import Struct

from cibot.storage_layers.base import BaseStorage


class PRContributor(Struct):
	pr_number: int
	pr_author_username: str
	pr_author_fullname: str | None


@dataclass
class ReleaseInfo:
	header: str
	note: str
	version: str
	
ERROR_GIF = "![](https://media1.tenor.com/m/FOzbM2mVKG0AAAAC/error-windows-xp.gif)"


class PrDescription(Struct):
	contributor: PRContributor
	header: str
	description: str
	pr_number: int


class CiBotBackendBase(ABC):
	def __init__(self, storage: BaseStorage) -> None:
		super().__init__()

	@abstractmethod
	def name(self) -> str: ...

	@abstractmethod
	def create_pr_comment(self, content: str) -> None: ...

	@abstractmethod
	def publish_release(self, release_info: ReleaseInfo) -> None: ...
	
	def run_cmd(self, *args: str) -> None:
		return subprocess.run([*args], check=False).check_returncode()

	def git(self, *args: str) -> None:
		return subprocess.run(["git", *args], check=False).check_returncode()

	@abstractmethod
	def get_pr_description(self, pr_number: int) -> PrDescription: ...

	@abstractmethod
	def get_commit_associated_pr(self, commit_hash: str) -> PrDescription: ...

	@abstractmethod
	def get_pr_labels(self, pr_number: int) -> list[str]: ...

	@abstractmethod
	def configure_git(self) -> None: ...

	def get_current_commit_hash(self) -> str:
		return (
			subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True)
			.stdout.decode()
			.strip()
		)
