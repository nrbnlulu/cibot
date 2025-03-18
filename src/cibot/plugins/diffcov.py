import xml.etree.ElementTree as etree
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import override

import jinja2
from diff_cover.diff_reporter import GitDiffReporter
from diff_cover.git_diff import GitDiffTool
from diff_cover.report_generator import MarkdownReportGenerator
from diff_cover.violationsreporters.violations_reporter import (
	XmlCoverageReporter,
)
from pydantic_settings import BaseSettings

from cibot.plugins.base import BumpType, CiBotPlugin

template_env = jinja2.Environment(
	loader=jinja2.FileSystemLoader(Path(__file__).parent / "templates"),
	autoescape=jinja2.select_autoescape(),
)

COVERAGE_TEMPLATE = template_env.get_template("coverage.jinja.md")


def create_report_for_cov_file(cov_file: Path, compare_branch: str) -> str | None:
	git_diff = GitDiffTool(range_notation="...", ignore_whitespace=True)
	git_diff_reporter = GitDiffReporter(
		git_diff=git_diff,
		include_untracked=True,
		ignore_staged=False,
		ignore_unstaged=False,
	)

	def _generate_section_report(
		reporter: XmlCoverageReporter,
	) -> str:
		"""Generate report for a single section."""
		with BytesIO() as buffer:
			markdown_gen = MarkdownReportGenerator(reporter, git_diff_reporter)
			markdown_gen.generate_report(buffer)
			markdown_string = buffer.getvalue().decode("utf-8").replace("# Diff Coverage", "")
			return markdown_string.replace(
				"## Diff: origin/main...HEAD, staged, unstaged and untracked changes",
				"",
			)

	section_name = cov_file.parent.name
	reporter = XmlCoverageReporter(
		[etree.parse(cov_file)],
		src_roots=[Path.cwd()],
	)
	section_md = _generate_section_report(reporter)
	if "No lines with coverage information in this diff." not in section_md:
		return section_md


class DiffCovSettings(BaseSettings):
	model_config = {
		"env_prefix": "DIFF_COV_",
	}
	COMPARE_BRANCH: str = "main"
	RECURSIVE: bool = True
	"""Find coverage files recursively"""


@dataclass
class CovReport:
	content: str
	header: str


class DiffCovPlugin(CiBotPlugin):
	
	@override
	def plugin_name(self) -> str:
		return "Diff Coverage"
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
		sections: dict[str, CovReport] = {}
		for cov_file in cov_files:
			section_name = cov_file.parent.name
			if content := create_report_for_cov_file(cov_file, settings.COMPARE_BRANCH):
				header = f"## {section_name} Coverage"
				report = CovReport(content=content, header=header)
				sections[section_name] = report
		comment = COVERAGE_TEMPLATE.render(
			sections=sections,
		)
		self.backend.create_pr_comment(comment, DIFF_COV_COMMENT_ID)


DIFF_COV_COMMENT_ID = "diffcov-766f-49c7-a1a8-59f7be1fee8f"
