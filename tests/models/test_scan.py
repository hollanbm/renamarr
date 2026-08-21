import pytest

from renamarr.models.scan import ScanFailure, ScanPhase, ScanResult, WorkSummary


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            ScanResult(0, WorkSummary(), WorkSummary(), WorkSummary(), ()),
            id="empty-library",
        ),
        pytest.param(
            ScanResult(
                1,
                WorkSummary(),
                WorkSummary(),
                WorkSummary(),
                (ScanFailure(ScanPhase.DISCOVERY, (), "failed"),),
            ),
            id="recorded-failure",
        ),
        pytest.param(
            ScanResult(1, WorkSummary(failed=1), WorkSummary(), WorkSummary(), ()),
            id="analysis-failure",
        ),
        pytest.param(
            ScanResult(1, WorkSummary(), WorkSummary(failed=1), WorkSummary(), ()),
            id="file-failure",
        ),
        pytest.param(
            ScanResult(1, WorkSummary(), WorkSummary(), WorkSummary(failed=1), ()),
            id="folder-failure",
        ),
    ],
)
def test_scan_result_reports_unsuccessful_outcomes(result: ScanResult) -> None:
    assert not result.successful


def test_scan_result_reports_success() -> None:
    result = ScanResult(
        1,
        WorkSummary(success=1),
        WorkSummary(skipped=1),
        WorkSummary(skipped=1),
        (),
    )

    assert result.successful
