"""Tool registry — imports all tools and exports them for graph binding."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from src.tools.bash import run_command
from src.tools.file_ops import edit_file, read_file, write_file
from src.tools.search import list_files, search_files

tools: list[BaseTool] = [read_file, edit_file, write_file, list_files, search_files, run_command]

tools_by_name: dict[str, BaseTool] = {t.name: t for t in tools}
