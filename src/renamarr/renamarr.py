import time
from collections import Counter
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import PurePosixPath
from typing import NoReturn

from loguru import logger
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandPollingSettings, CommandStatus
from renamarr.models.media import FileRenameCandidate, FolderRenameBatch, MediaItem
from renamarr.models.scan import ScanFailure, ScanPhase, ScanResult, WorkSummary
from renamarr.protocols import ArrAdapter
from renamarr.telemetry import Operation, WorkflowTelemetry, disabled_workflow

_DEFAULT_COMMAND_POLLING = CommandPollingSettings()


class _WorkOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Renamarr:
    """Run the shared rename workflow through an Arr adapter."""

    def __init__(
        self,
        name: str,
        adapter: ArrAdapter,
        analyze_files: bool = False,
        rename_folders: bool = False,
        command_polling: CommandPollingSettings = _DEFAULT_COMMAND_POLLING,
        telemetry: WorkflowTelemetry | None = None,
    ) -> None:
        self.name = name
        self.adapter = adapter
        self.analyze_files = analyze_files
        self.rename_folders = rename_folders
        self.command_polling = command_polling
        self.telemetry = telemetry if telemetry is not None else disabled_workflow()

    def scan(self) -> ScanResult:
        """Run a scan and return its structured outcome."""
        with logger.contextualize(instance=self.name):
            logger.info("Starting Renamarr")
            failures: list[ScanFailure] = []
            with self.telemetry.phase("analysis"):
                analysis_outcome, analysis_error = self._analyze_media()

            try:
                with self.telemetry.phase("discovery"):
                    items = sorted(
                        self.adapter.list_media_items(), key=lambda item: item.title
                    )
            except ArrOperationError as error:
                analysis = self._summarize_analysis(
                    analysis_outcome, analysis_error, (), failures
                )
                self._record_failure(failures, ScanPhase.DISCOVERY, (), error)
                return self._finish_scan(
                    0, analysis, WorkSummary(), WorkSummary(), failures
                )

            if not items:
                analysis = self._summarize_analysis(
                    analysis_outcome, analysis_error, (), failures
                )
                self._record_failure(
                    failures,
                    ScanPhase.DISCOVERY,
                    (),
                    ArrOperationError("Media library is empty"),
                )
                return self._finish_scan(
                    0, analysis, WorkSummary(), WorkSummary(), failures
                )

            analysis = self._summarize_analysis(
                analysis_outcome, analysis_error, items, failures
            )
            with self.telemetry.phase("file_renames"):
                file_renames = self._rename_files(items, failures)
            if file_renames.failed > 0:
                logger.warning("Skipping folder renames because file renames failed")
                folder_renames = WorkSummary(skipped=len(items))
            else:
                with self.telemetry.phase("folder_renames"):
                    folder_renames = self._rename_folders(items, failures)
            return self._finish_scan(
                len(items), analysis, file_renames, folder_renames, failures
            )

    def _analyze_media(self) -> tuple[_WorkOutcome, ArrOperationError | None]:
        if not self.analyze_files:
            return _WorkOutcome.SKIPPED, None

        try:
            if not self.adapter.is_media_analysis_enabled():
                logger.warning("Media analysis is disabled in the Arr service")
                return _WorkOutcome.SKIPPED, None

            logger.info("Starting media analysis")
            command_id = self.adapter.start_media_analysis()
            self._wait_for_command(command_id, "media analysis", "analysis")
        except ArrOperationError as error:
            trace.get_current_span().set_status(StatusCode.ERROR)
            trace.get_current_span().record_exception(error)
            return _WorkOutcome.FAILED, error

        logger.info("Media analysis completed successfully")
        return _WorkOutcome.SUCCEEDED, None

    def _summarize_analysis(
        self,
        outcome: _WorkOutcome,
        error: ArrOperationError | None,
        items: Sequence[MediaItem],
        failures: list[ScanFailure],
    ) -> WorkSummary:
        if error is not None:
            self._record_failure(
                failures,
                ScanPhase.ANALYSIS,
                tuple(item.id for item in items),
                error,
            )
        return self._summarize(outcome for _ in items)

    def _rename_files(
        self, items: list[MediaItem], failures: list[ScanFailure]
    ) -> WorkSummary:
        outcomes: dict[int, _WorkOutcome] = {}
        candidates: list[FileRenameCandidate] = []

        for item in items:
            with logger.contextualize(item=item.title):
                try:
                    with self.telemetry.span(
                        "renamarr.preview.file",
                        {
                            "media.id": item.id,
                            "media.title": item.title,
                            "media.path": item.path,
                        },
                    ):
                        candidate = self.adapter.get_file_rename_candidate(item)
                except ArrOperationError as error:
                    outcomes[item.id] = _WorkOutcome.FAILED
                    self._record_failure(
                        failures, ScanPhase.FILE_RENAMES, (item.id,), error
                    )
                    continue

                if candidate is None:
                    logger.debug("No files need renaming")
                    outcomes[item.id] = _WorkOutcome.SKIPPED
                    continue

                self.telemetry.count(
                    "renamarr.rename.candidates",
                    len(set(candidate.file_ids)),
                    kind="file",
                )
                candidates.append(candidate)

        if not candidates:
            return self._summarize(outcomes.values())

        candidate_ids = tuple(candidate.item.id for candidate in candidates)
        candidates_by_id = {candidate.item.id: candidate for candidate in candidates}
        try:
            batches = self.adapter.build_file_rename_batches(candidates)
        except ArrOperationError as error:
            for item_id in candidate_ids:
                outcomes[item_id] = _WorkOutcome.FAILED
            self._record_failure(failures, ScanPhase.FILE_RENAMES, candidate_ids, error)
            return self._summarize(outcomes.values())

        batched_item_ids = [item_id for batch in batches for item_id in batch.item_ids]
        if Counter(batched_item_ids) != Counter(candidate_ids):
            raise ValueError(
                "File rename batches must contain every candidate exactly once"
            )

        for batch in batches:
            with self.telemetry.operation(
                "operation",
                "file",
                {
                    "media.ids": batch.item_ids,
                    "file.ids": batch.file_ids,
                    "description": batch.description,
                },
            ) as operation:
                logger.info(f"Renaming files: {batch.description}")
                try:
                    command_id = self.adapter.start_file_rename(batch)
                    self.telemetry.count(
                        "renamarr.rename.requested",
                        len(set(batch.file_ids)),
                        kind="file",
                    )
                    self._wait_for_command(
                        command_id, f"file rename: {batch.description}", "file_rename"
                    )
                except ArrOperationError as error:
                    operation.outcome = "failed"
                    for item_id in batch.item_ids:
                        outcomes[item_id] = _WorkOutcome.FAILED
                    self._record_failure(
                        failures, ScanPhase.FILE_RENAMES, batch.item_ids, error
                    )
                    continue

                for item_id in batch.item_ids:
                    candidate = candidates_by_id[item_id]
                    item = candidate.item
                    try:
                        with self.telemetry.span(
                            "renamarr.verification",
                            {
                                "media.id": item.id,
                                "media.title": item.title,
                                "media.path": item.path,
                                "file.ids": candidate.file_ids,
                            },
                        ):
                            remaining = self.adapter.get_file_rename_candidate(item)
                            if remaining is not None:
                                raise ArrOperationError(
                                    f"File rename incomplete for {item.title}: "
                                    f"file ID{'s' if len(remaining.file_ids) != 1 else ''} "
                                    f"{list(remaining.file_ids)} still "
                                    f"need{'s' if len(remaining.file_ids) == 1 else ''} renaming "
                                    f"after command {command_id}; check the Arr service logs for "
                                    "filename collisions or file access errors"
                                )
                    except ArrOperationError as error:
                        operation.outcome = "failed"
                        outcomes[item_id] = _WorkOutcome.FAILED
                        self._record_failure(
                            failures, ScanPhase.FILE_RENAMES, (item_id,), error
                        )
                        continue

                    self.telemetry.count(
                        "renamarr.rename.confirmed",
                        len(set(candidate.file_ids)),
                        kind="file",
                    )
                    outcomes[item_id] = _WorkOutcome.SUCCEEDED
                    logger.info(
                        f"File rename completed successfully: {candidate.description}"
                    )
        return self._summarize(outcomes.values())

    def _rename_folders(
        self, items: list[MediaItem], failures: list[ScanFailure]
    ) -> WorkSummary:
        if not self.rename_folders:
            return WorkSummary(skipped=len(items))

        outcomes: dict[int, _WorkOutcome] = {}
        try:
            root_folders = self.adapter.list_root_folders()
        except ArrOperationError as error:
            item_ids = tuple(item.id for item in items)
            self._record_failure(failures, ScanPhase.FOLDER_RENAMES, item_ids, error)
            return WorkSummary(failed=len(items))

        grouped_items: dict[str, list[MediaItem]] = {}
        for item in items:
            with logger.contextualize(item=item.title):
                root_folder = self._find_root_folder(item, root_folders)
                if root_folder is None:
                    outcomes[item.id] = _WorkOutcome.FAILED
                    self._record_failure(
                        failures,
                        ScanPhase.FOLDER_RENAMES,
                        (item.id,),
                        ArrOperationError(
                            f"No root folder matches media path {item.path}"
                        ),
                    )
                    continue

                try:
                    with self.telemetry.span(
                        "renamarr.preview.folder",
                        {
                            "media.id": item.id,
                            "media.title": item.title,
                            "media.path": item.path,
                        },
                    ):
                        expected_folder_name = self.adapter.get_expected_folder_name(
                            item
                        )
                except ArrOperationError as error:
                    outcomes[item.id] = _WorkOutcome.FAILED
                    self._record_failure(
                        failures, ScanPhase.FOLDER_RENAMES, (item.id,), error
                    )
                    continue

                expected_path = PurePosixPath(root_folder) / expected_folder_name
                if expected_path == PurePosixPath(item.path):
                    logger.debug("Media folder is already correctly named")
                    outcomes[item.id] = _WorkOutcome.SKIPPED
                    continue

                self.telemetry.count("renamarr.rename.candidates", kind="folder")
                grouped_items.setdefault(root_folder, []).append(item)

        for root_folder, batch_items in grouped_items.items():
            batch = FolderRenameBatch(root_folder, tuple(batch_items))
            with self.telemetry.operation(
                "operation",
                "folder",
                {
                    "media.ids": batch.item_ids,
                    "media.titles": batch.titles,
                    "folder.root": root_folder,
                    "media.paths": tuple(item.path for item in batch.items),
                },
            ) as operation:
                logger.info(f"Renaming folders: {', '.join(batch.titles)}")
                try:
                    move_command_id = self.adapter.move_folder(batch)
                    self.telemetry.count(
                        "renamarr.rename.requested", len(batch.items), kind="folder"
                    )
                    if move_command_id is not None:
                        self._wait_for_command(
                            move_command_id,
                            f"folder move: {', '.join(batch.titles)}",
                            "folder_move",
                        )
                    command_id = self.adapter.start_folder_rescan(batch)
                    self._wait_for_command(
                        command_id,
                        f"folder rescan: {', '.join(batch.titles)}",
                        "folder_rescan",
                    )
                except ArrOperationError as error:
                    operation.outcome = "failed"
                    for item_id in batch.item_ids:
                        outcomes[item_id] = _WorkOutcome.FAILED
                    self._record_failure(
                        failures, ScanPhase.FOLDER_RENAMES, batch.item_ids, error
                    )
                    continue

                self.telemetry.count(
                    "renamarr.rename.confirmed", len(batch.items), kind="folder"
                )
                for item_id in batch.item_ids:
                    outcomes[item_id] = _WorkOutcome.SUCCEEDED
                logger.info(
                    f"Folder workflow completed successfully: {', '.join(batch.titles)}"
                )
        return self._summarize(outcomes.values())

    def _wait_for_command(
        self, command_id: int, description: str, kind: str = "command"
    ) -> None:
        with self.telemetry.operation(
            "command", kind, {"command.id": command_id, "description": description}
        ) as operation:
            self._poll_command(command_id, description, kind, operation)

    def _poll_command(
        self, command_id: int, description: str, kind: str, operation: Operation
    ) -> None:
        started_at = time.monotonic()
        status = self._command_status(command_id, kind, operation)

        while not status.completed:
            elapsed_seconds = time.monotonic() - started_at
            if self._deadline_exceeded(elapsed_seconds, inclusive=True):
                operation.outcome = "timed_out"
                self._raise_timeout(command_id, description)
            time.sleep(
                min(
                    self.command_polling.check_interval_seconds,
                    self.command_polling.timeout_seconds - elapsed_seconds,
                )
            )
            if self._deadline_exceeded(time.monotonic() - started_at, inclusive=False):
                operation.outcome = "timed_out"
                self._raise_timeout(command_id, description)
            status = self._command_status(command_id, kind, operation)

        if not status.successful:
            operation.outcome = "failed"
            normalized_description = description[:1].upper() + description[1:]
            raise ArrOperationError(
                f"{normalized_description} command {command_id} completed unsuccessfully"
            )

    def _command_status(
        self, command_id: int, kind: str, operation: Operation
    ) -> CommandStatus:
        self.telemetry.count("renamarr.command.polls", kind=kind)
        try:
            return self.adapter.get_command_status(command_id)
        except ArrOperationError:
            operation.outcome = "status_check_error"
            raise

    def _deadline_exceeded(self, elapsed_seconds: float, *, inclusive: bool) -> bool:
        if inclusive:
            return elapsed_seconds >= self.command_polling.timeout_seconds
        return elapsed_seconds > self.command_polling.timeout_seconds

    def _raise_timeout(self, command_id: int, description: str) -> NoReturn:
        raise ArrOperationError(
            f"Timed out waiting for {description} command {command_id} "
            f"after {self.command_polling.timeout_seconds} seconds"
        )

    @staticmethod
    def _find_root_folder(item: MediaItem, root_folders: list[str]) -> str | None:
        item_path = PurePosixPath(item.path)
        matching_roots = [
            (PurePosixPath(root_folder), root_folder)
            for root_folder in root_folders
            if PurePosixPath(root_folder) == item_path
            or PurePosixPath(root_folder) in item_path.parents
        ]
        if not matching_roots:
            return None
        return max(matching_roots, key=lambda match: len(match[0].parts))[1]

    @staticmethod
    def _summarize(outcomes: Iterable[_WorkOutcome]) -> WorkSummary:
        counts = Counter(outcomes)
        return WorkSummary(
            success=counts[_WorkOutcome.SUCCEEDED],
            failed=counts[_WorkOutcome.FAILED],
            skipped=counts[_WorkOutcome.SKIPPED],
        )

    @staticmethod
    def _record_failure(
        failures: list[ScanFailure],
        phase: ScanPhase,
        item_ids: tuple[int, ...],
        error: ArrOperationError,
    ) -> None:
        trace.get_current_span().set_status(StatusCode.ERROR)
        trace.get_current_span().record_exception(error)
        logger.error(str(error))
        failures.append(ScanFailure(phase, item_ids, str(error)))

    def _finish_scan(
        self,
        items_found: int,
        analysis: WorkSummary,
        file_renames: WorkSummary,
        folder_renames: WorkSummary,
        failures: list[ScanFailure],
    ) -> ScanResult:
        result = ScanResult(
            items_found=items_found,
            analysis=analysis,
            file_renames=file_renames,
            folder_renames=folder_renames,
            failures=tuple(failures),
        )
        self.telemetry.finish_scan(result)
        logger.debug(
            f"Items found: {items_found} | analysis: [ success={analysis.success}, "
            f"failed={analysis.failed}, skipped={analysis.skipped} ]"
        )
        summary = (
            f"file renames: [ success={file_renames.success}, "
            f"failed={file_renames.failed}, skipped={file_renames.skipped} ] | "
            f"folder renames: [ success={folder_renames.success}, "
            f"failed={folder_renames.failed}, skipped={folder_renames.skipped} ]"
        )
        if result.successful:
            logger.info(f"Finished Renamarr successfully | {summary}")
        else:
            logger.error(
                f"Finished Renamarr with {len(result.failures)} failures | {summary}"
            )
        return result
