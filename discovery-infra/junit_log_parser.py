#!/usr/bin/env python3
import re
import uuid
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

from junit_xml import TestCase, TestSuite, to_xml_report_string

from logger import log, SuppressAndLog


@dataclass
class CaseFailure:
    message: str
    output: str = ""
    type: str = ""

    def __getitem__(self, item):
        return self.__getattribute__(item)


@dataclass
class LogEntry:
    time: str = None
    level: str = None
    msg: str = None
    func: str = None
    file: str = None
    error: Optional[str] = None


LOG_FORMAT = r'time="(?P<time>(.*?))" ' \
             r'level=(?P<level>(.*?)) ' \
             r'msg="(?P<msg>.*)" ' \
             r'func=(?P<func>.*) ' \
             r'file="(?P<file>(.*?))" ' \
             r'(error="(?P<error>.*)")?'


EXPORTED_LOG_LEVELS = ("fatal", "error")
EXPORTED_EVENT_LEVELS = ("critical", "error")


def is_duplicate_entry(entry: LogEntry, entry_message: str, fail_cases: Dict[str, List[TestCase]]) -> bool:
    for case in fail_cases.get(entry.func, []):
        if case.failures and case.failures[0].message == entry_message:
            return True
    return False


def get_log_entry_case(entry: LogEntry, fail_cases: Dict[str, List[TestCase]], suite_name: str) -> List[TestCase]:
    fail_case: List[TestCase] = list()
    message = f"{entry.msg}\n{entry.error if entry.error else ''}"

    if is_duplicate_entry(entry, message, fail_cases):
        return []

    test_case = TestCase(name=entry.func, classname=suite_name, category=suite_name, timestamp=entry.time)
    test_case.failures.append(CaseFailure(message=message, output=message, type=entry.level))
    fail_case.append(test_case)

    if entry.level != "fatal":
        # Add test case with the same name so it will be marked in PROW as flaky
        flaky_test_case = TestCase(name=entry.func, classname=suite_name, category=suite_name)
        fail_case.append(flaky_test_case)

    return fail_case


def get_failure_cases(log_file_name: Path, suite_name: str) -> List[TestCase]:
    fail_cases: Dict[str, List[TestCase]] = dict()

    with open(log_file_name) as f:
        for line in f:
            values = re.match(LOG_FORMAT, line)
            if values is None:
                continue

            entry = LogEntry(**values.groupdict())
            if entry.level not in EXPORTED_LOG_LEVELS:
                continue
            if entry.func not in fail_cases:
                fail_cases[entry.func] = list()
            fail_cases[entry.func] += get_log_entry_case(entry, fail_cases, suite_name)

    log.info(f"Found {len(fail_cases)} failures on {suite_name} suite")
    return [c for cases in fail_cases.values() for c in cases]


def export_service_logs_to_junit_suites(source_dir: Path, report_dir: Path):
    suites = list()
    for file in source_dir.glob("k8s_assisted-service*.log"):
        suite_name = Path(file).stem.replace("k8s_", "")
        log.info(f"Creating test suite from {suite_name}.log")
        test_cases = get_failure_cases(file, suite_name)
        timestamp = test_cases[0].timestamp if test_cases else None
        suites.append(TestSuite(name=suite_name, test_cases=test_cases, timestamp=timestamp))

    log.info(f"Generating xml file for {len(suites)} suites")
    xml_report = to_xml_report_string(suites)
    with open(report_dir.joinpath(f"junit_log_parser_{str(uuid.uuid4())[:8]}.xml"), "w") as f:
        log.info(f"Exporting {len(suites)} suites xml-report with {len(xml_report)} characters to {f.name}")
        f.write(xml_report)


def main():
    parser = ArgumentParser(description="Logs junit parser")
    parser.add_argument("--src", help="Logs dir source", type=str)
    parser.add_argument("--dst", help="Junit XML report destination", type=str)
    args = parser.parse_args()

    report_dir = Path(args.dst)
    report_dir.mkdir(exist_ok=True)

    with SuppressAndLog(BaseException):
        log.info(f"Parsing logs from `{args.src}` to `{report_dir}`")
        export_service_logs_to_junit_suites(Path(args.src), report_dir)


if __name__ == '__main__':
    log.info("Initializing attempt for creating JUNIT report from service logs")
    main()