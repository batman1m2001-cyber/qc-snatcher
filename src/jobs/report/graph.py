"""`report` — the end-of-batch summary, read from the score run's record.

    summarize
"""
from operonx.core import END, START, graph

from .ops import summarize


@graph
def report(input_path: str, files_list: str, output_path: str, record_dir: str):
    summary = summarize(
        input_path=input_path,
        files_list=files_list,
        output_path=output_path,
        record_dir=record_dir,
    )
    START >> summary >> END
