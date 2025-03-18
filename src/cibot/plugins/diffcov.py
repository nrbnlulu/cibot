import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TypedDict, override

import jinja2
from diff_cover.diff_reporter import GitDiffReporter
from diff_cover.report_generator import MarkdownReportGenerator
from diff_cover.violationsreporters.violations_reporter import (
	XmlCoverageReporter,
)
from loguru import logger
from pydantic_settings import BaseSettings

from cibot.backends.base import PrReviewComment
from cibot.plugins.base import BumpType, CiBotPlugin

template_env = jinja2.Environment(
	loader=jinja2.FileSystemLoader(Path(__file__).parent / "templates"),
	autoescape=jinja2.select_autoescape(),
)

COVERAGE_TEMPLATE = template_env.get_template("coverage.jinja.md")


def _generate_section_report(
	reporter: XmlCoverageReporter, git_diff_reporter: GitDiffReporter, compare_branch: str
) -> str:
	"""Generate report for a single section."""
	with BytesIO() as buffer:
		markdown_gen = MarkdownReportGenerator(reporter, git_diff_reporter)
		markdown_gen.generate_report(buffer)
		markdown_string = buffer.getvalue().decode("utf-8").replace("# Diff Coverage", "")
		# strip first header
		markdown_string = markdown_string[markdown_string.find("\n") + 1 :]
		return markdown_string


class DiffCovSettings(BaseSettings):
	model_config = {
		"env_prefix": "DIFF_COV_",
	}
	COMPARE_BRANCH: str = "main"
	RECURSIVE: bool = True
	"""Find coverage files recursively"""


class DiffCovPlugin(CiBotPlugin):
	@override
	def plugin_name(self) -> str:
		return "Diff Coverage"

	@override
	def supported_backends(self) -> tuple[str, ...]:
		return ("*",)

	@property
	def settings(self) -> DiffCovSettings:
		return DiffCovSettings()

	@override
	def on_pr_changed(self, pr: int) -> BumpType | None:
		settings = self.settings
		cov_files = []
		if settings.RECURSIVE:
			cov_files = list(Path.cwd().rglob("coverage.xml"))
		else:
			cov_files = [Path.cwd() / "coverage.xml"]
		for cov_file in cov_files:
			section_name = cov_file.parent.name
			report = create_report_for_cov_file(cov_file, settings.COMPARE_BRANCH)
			grouped_lines_per_file: defaultdict[str, list[tuple[int, int | None]]] = defaultdict(
				list
			)
			for file, stats in report["src_stats"].items():
				violation_lines = stats.get("violation_lines", [])
				if violation_lines:
					for i, start in enumerate(violation_lines):
						try:
							prev = start
							for end in violation_lines[i + 1 :]:
								if end - 1 == prev:
									prev = end
									continue
								grouped_lines_per_file[file].append((start, end))
						except IndexError:
							grouped_lines_per_file[file].append((start, None))
			valid_comments: list[tuple[PrReviewComment, tuple[int, int | None]]] = []
			for id_, comment in self.backend.get_review_comments_for_content_id(
				DIFF_COV_REVIEW_COMMENT_ID
			):
				if comment.file not in grouped_lines_per_file:
					logger.info(
						f"{comment.file} is not in the missed cov report deleting prev comment"
					)
					self.backend.delete_pr_review_comment(id_)
					continue
				for violation in grouped_lines_per_file[comment.file]:
					if violation[0] != comment.start_line and violation[0] != comment.end_line:
						logger.add(
							f"Deleting comment {id_} for file {comment.file} in lines {violation[0]}-{violation[1]}"
						)
						self.backend.delete_pr_review_comment(id_)
						break
					valid_comments.append((comment, violation))

			for file, violations in grouped_lines_per_file.items():
				for violation in violations:
					for valid_comment, comment_violation in valid_comments:
						if (
							comment_violation[0] == violation[0]
							and comment_violation[1] == violation[1]
						):
							logger.info(
								f"skipping creating review comment for violation {file} {violation}"
							)
							break
						logger.info(
							f"Creating new comment for file {violation[0]} in lines {violation[0]}-{violation[1]}"
						)
						self.backend.create_pr_review_comment(
							PrReviewComment(
								content="not covered",
								content_id=DIFF_COV_REVIEW_COMMENT_ID,
								start_line=violation[0] if violation[1] else None,
								end_line=violation[1] if violation[1] else violation[0],
								file=file,
								pr_number=pr,
							)
						)


DIFF_COV_REVIEW_COMMENT_ID = "diffcov-766f-49c7-a1a8-59f7be1fee8f"


class FileStats(TypedDict):
	percent_covered: float
	violation_lines: list[int]
	covered_lines: list[int]


class Report(TypedDict):
	report_name: str
	diff_name: str
	src_stats: dict[str, FileStats]
	total_num_lines: int
	total_num_violations: int
	total_percent_covered: float
	num_changed_lines: int


def create_report_for_cov_file(cov_file: Path, compare_branch: str) -> Report:
	cmd = f"diff-cover coverage.xml --compare-branch={compare_branch} --json-report report.json"
	if subprocess.run(cmd, shell=True, check=False).returncode != 0:
		raise ValueError("Failed to generate coverage report")

	report: Report = json.loads((Path.cwd() / "report.json").read_text())
	return report


@dataclass
class CovReport:
	header: str
	content: Report
