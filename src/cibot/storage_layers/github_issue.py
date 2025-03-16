import contextlib
import json
import textwrap

from loguru import logger
import msgspec
from pydantic_settings import BaseSettings
from github.Repository import Repository
from cibot.storage_layers.base import BaseStorage


class Settings(BaseSettings):
	model_config = {
		"env_prefix": "CIBOT_STORAGE_GH_ISSUE_",
	}
	number: int | None = None


class Bucket(msgspec.Struct):
	plugin_srorage: dict[str, str]


class GithubIssueStorage(BaseStorage):
	def __init__(self, repo: Repository) -> None:
		settings = Settings()
		if not settings.number:
			raise ValueError("missing STORAGE_ISSUE_NUMBER")
		issue = repo.get_issue(settings.number)
		logger.info(f"Found issue {issue.title}")
		self.issue = issue

	def get_json_part_from_comment(self) -> Bucket | None:
		body = self.issue.body
		logger.info(f"Checking issue body: {body}")
		if body:
			body = body.split("```json")[1].split("```")[0].strip()
			return msgspec.json.decode(body, type=Bucket)

	def get[T](self, key: str, type_: type[T]) -> T | None:
		if bucket := self.get_json_part_from_comment():
			return msgspec.json.decode(bucket.plugin_srorage[key], type=type_)
		return None

	def set(self, key: str, value: msgspec.Struct) -> None:
		raw = msgspec.json.encode(value).decode()
		comment_base = """
### CIBot Storage Layer
### Do not edit this comment
```json
{}
```
"""
		if bucket := self.get_json_part_from_comment():
			logger.info(f"Updating key {key} with value {raw}")
			bucket.plugin_srorage[key] = raw
			new_comment = comment_base.format(json.dumps(msgspec.to_builtins(bucket), indent=2))
		else:
			logger.info(f"Creating new bucket with key {key} with value {raw}")
			new_comment = comment_base.format(
				json.dumps(msgspec.to_builtins(Bucket(plugin_srorage={key: raw})), indent=2)
			)
		self.issue.edit(body=textwrap.dedent(new_comment))
