import time
from collections import Counter
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import PurePosixPath

from loguru import logger

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandPollingSettings
from renamarr.models.media import FileRenameCandidate, FolderRenameBatch, MediaItem
from renamarr.models.scan import ScanFailure, ScanPhase, ScanResult, WorkSummary
from renamarr.protocols import ArrAdapter

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
    ) -> None:
        self.name = name
        self.adapter = adapter
        self.analyze_files = analyze_files
        self.rename_folders = rename_folders
        self.command_polling = command_polling

    def scan(self) -> ScanResult:
        """Run a scan and return its structured outcome."""
        with logger.contextualize(instance=self.name):
            logger.info("Starting Renamarr")
            failures: list[ScanFailure] = []
            analysis_outcome, analysis_error = self._analyze_media()

            try:
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
            file_renames = self._rename_files(items, failures)
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
            self._wait_for_command(command_id, "media analysis")
        except ArrOperationError as error:
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

                candidates.append(candidate)

        if not candidates:
            return self._summarize(outcomes.values())

        candidate_ids = tuple(candidate.item.id for candidate in candidates)
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
            logger.info(f"Renaming files: {batch.description}")
            try:
                command_id = self.adapter.start_file_rename(batch)
                self._wait_for_command(command_id, f"file rename: {batch.description}")
            except ArrOperationError as error:
                for item_id in batch.item_ids:
                    outcomes[item_id] = _WorkOutcome.FAILED
                self._record_failure(
                    failures, ScanPhase.FILE_RENAMES, batch.item_ids, error
                )
                continue

            for item_id in batch.item_ids:
                outcomes[item_id] = _WorkOutcome.SUCCEEDED
            logger.info(f"File rename completed successfully: {batch.description}")

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
                    expected_folder_name = self.adapter.get_expected_folder_name(item)
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

                grouped_items.setdefault(root_folder, []).append(item)

        for root_folder, batch_items in grouped_items.items():
            batch = FolderRenameBatch(root_folder, tuple(batch_items))
            logger.info(f"Renaming folders: {', '.join(batch.titles)}")
            try:
                self.adapter.move_folder(batch)
                command_id = self.adapter.start_folder_rescan(batch)
                self._wait_for_command(
                    command_id, f"folder rescan: {', '.join(batch.titles)}"
                )
            except ArrOperationError as error:
                for item_id in batch.item_ids:
                    outcomes[item_id] = _WorkOutcome.FAILED
                self._record_failure(
                    failures, ScanPhase.FOLDER_RENAMES, batch.item_ids, error
                )
                continue

            for item_id in batch.item_ids:
                outcomes[item_id] = _WorkOutcome.SUCCEEDED
            logger.info(
                f"Folder workflow completed successfully: {', '.join(batch.titles)}"
            )

        return self._summarize(outcomes.values())

    def _wait_for_command(self, command_id: int, description: str) -> None:
        started_at = time.monotonic()
        status = self.adapter.get_command_status(command_id)

        while not status.completed:
            elapsed_seconds = time.monotonic() - started_at
            if self._deadline_exceeded(elapsed_seconds, inclusive=True):
                self._raise_timeout(command_id, description)
            time.sleep(
                min(
                    self.command_polling.check_interval_seconds,
                    self.command_polling.timeout_seconds - elapsed_seconds,
                )
            )
            if self._deadline_exceeded(time.monotonic() - started_at, inclusive=False):
                self._raise_timeout(command_id, description)
            status = self.adapter.get_command_status(command_id)

        if not status.successful:
            normalized_description = description[:1].upper() + description[1:]
            raise ArrOperationError(
                f"{normalized_description} command {command_id} completed unsuccessfully"
            )

    def _deadline_exceeded(self, elapsed_seconds: float, *, inclusive: bool) -> bool:
        if inclusive:
            return elapsed_seconds >= self.command_polling.timeout_seconds
        return elapsed_seconds > self.command_polling.timeout_seconds

    def _raise_timeout(self, command_id: int, description: str) -> None:
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
        logger.error(str(error))
        failures.append(ScanFailure(phase, item_ids, str(error)))

    @staticmethod
    def _finish_scan(
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
