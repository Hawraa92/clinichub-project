from types import SimpleNamespace

from django.test import SimpleTestCase

from ecg.services.quality_assessment import (
    ECGQualityAssessmentError,
    assess_ecg_processing_quality,
)


class ECGQualityAssessmentTests(SimpleTestCase):
    def create_reconstructed_signal(
        self,
        *,
        coverage_ratio=1.0,
        sample_count=100,
        missing_count=0,
    ):
        return SimpleNamespace(
            coverage_ratio=coverage_ratio,
            sample_count=sample_count,
            missing_count=missing_count,
        )

    def create_lead_layout(
        self,
        *,
        row_count=3,
        cell_count=12,
    ):
        return SimpleNamespace(
            row_count=row_count,
            cell_count=cell_count,
        )

    def create_grid_detection(
        self,
        *,
        pixels_per_mm=5.0,
    ):
        return SimpleNamespace(
            pixels_per_mm=pixels_per_mm,
        )

    def test_complete_signal_is_high_quality(self):
        signal = self.create_reconstructed_signal(
            coverage_ratio=1.0,
            sample_count=100,
            missing_count=0,
        )

        result = assess_ecg_processing_quality(
            signal
        )

        self.assertTrue(
            result.usable
        )

        self.assertEqual(
            result.quality_level,
            "high",
        )

        self.assertTrue(
            result.high_quality
        )

        self.assertFalse(
            result.insufficient_quality
        )

        self.assertEqual(
            result.coverage_ratio,
            1.0,
        )

        self.assertEqual(
            result.coverage_percent,
            100.0,
        )

        self.assertEqual(
            result.reasons,
            (),
        )

        self.assertEqual(
            result.warnings,
            (),
        )

    def test_incomplete_but_usable_signal_is_acceptable(self):
        signal = self.create_reconstructed_signal(
            coverage_ratio=0.95,
            sample_count=100,
            missing_count=5,
        )

        result = assess_ecg_processing_quality(
            signal
        )

        self.assertTrue(
            result.usable
        )

        self.assertEqual(
            result.quality_level,
            "acceptable",
        )

        self.assertFalse(
            result.high_quality
        )

        self.assertEqual(
            result.warnings,
            (
                (
                    "The ECG signal is usable but contains "
                    "incomplete reconstructed coverage."
                ),
                (
                    "The reconstructed ECG signal contains "
                    "missing samples."
                ),
            ),
        )

    def test_low_coverage_signal_is_insufficient(self):
        signal = self.create_reconstructed_signal(
            coverage_ratio=0.80,
            sample_count=100,
            missing_count=20,
        )

        result = assess_ecg_processing_quality(
            signal
        )

        self.assertFalse(
            result.usable
        )

        self.assertEqual(
            result.quality_level,
            "insufficient",
        )

        self.assertTrue(
            result.insufficient_quality
        )

        self.assertIn(
            (
                "The reconstructed ECG signal coverage "
                "is below the minimum usable threshold."
            ),
            result.reasons,
        )

    def test_signal_with_too_few_samples_is_insufficient(self):
        signal = self.create_reconstructed_signal(
            coverage_ratio=1.0,
            sample_count=5,
            missing_count=0,
        )

        result = assess_ecg_processing_quality(
            signal
        )

        self.assertFalse(
            result.usable
        )

        self.assertEqual(
            result.quality_level,
            "insufficient",
        )

        self.assertIn(
            (
                "The reconstructed ECG signal contains "
                "too few samples."
            ),
            result.reasons,
        )

    def test_layout_is_reported_when_available(self):
        signal = self.create_reconstructed_signal()

        layout = self.create_lead_layout(
            row_count=3,
            cell_count=12,
        )

        result = assess_ecg_processing_quality(
            signal,
            lead_layout=layout,
        )

        self.assertTrue(
            result.layout_detected
        )

        self.assertEqual(
            result.layout_row_count,
            3,
        )

        self.assertEqual(
            result.layout_cell_count,
            12,
        )

    def test_missing_layout_is_rejected_when_required(self):
        signal = self.create_reconstructed_signal()

        result = assess_ecg_processing_quality(
            signal,
            require_layout=True,
        )

        self.assertFalse(
            result.usable
        )

        self.assertEqual(
            result.quality_level,
            "insufficient",
        )

        self.assertIn(
            "A detected ECG lead layout is required.",
            result.reasons,
        )

    def test_required_layout_allows_valid_layout(self):
        signal = self.create_reconstructed_signal()

        layout = self.create_lead_layout(
            row_count=3,
            cell_count=12,
        )

        result = assess_ecg_processing_quality(
            signal,
            lead_layout=layout,
            require_layout=True,
        )

        self.assertTrue(
            result.usable
        )

        self.assertTrue(
            result.layout_detected
        )

    def test_grid_detection_is_reported_when_available(self):
        signal = self.create_reconstructed_signal()

        grid_detection = (
            self.create_grid_detection(
                pixels_per_mm=5.0
            )
        )

        result = assess_ecg_processing_quality(
            signal,
            grid_detection=grid_detection,
        )

        self.assertTrue(
            result.grid_detected
        )

        self.assertTrue(
            result.usable
        )

    def test_missing_grid_is_rejected_when_required(self):
        signal = self.create_reconstructed_signal()

        result = assess_ecg_processing_quality(
            signal,
            require_grid=True,
        )

        self.assertFalse(
            result.usable
        )

        self.assertIn(
            "ECG grid detection is required.",
            result.reasons,
        )

    def test_missing_calibration_is_rejected_when_required(self):
        signal = self.create_reconstructed_signal()

        result = assess_ecg_processing_quality(
            signal,
            require_calibration=True,
        )

        self.assertFalse(
            result.usable
        )

        self.assertFalse(
            result.calibrated
        )

        self.assertIn(
            "ECG signal calibration is required.",
            result.reasons,
        )

    def test_calibration_is_reported_when_available(self):
        signal = self.create_reconstructed_signal()

        calibrated_signal = object()

        result = assess_ecg_processing_quality(
            signal,
            calibrated_signal=calibrated_signal,
            require_calibration=True,
        )

        self.assertTrue(
            result.calibrated
        )

        self.assertTrue(
            result.usable
        )

    def test_reconstructed_signal_is_required(self):
        with self.assertRaises(
            ECGQualityAssessmentError
        ):
            assess_ecg_processing_quality(
                None
            )

    def test_invalid_coverage_ratio_is_rejected(self):
        signal = self.create_reconstructed_signal(
            coverage_ratio=1.5,
        )

        with self.assertRaises(
            ECGQualityAssessmentError
        ):
            assess_ecg_processing_quality(
                signal
            )

    def test_missing_count_cannot_exceed_sample_count(self):
        signal = self.create_reconstructed_signal(
            sample_count=10,
            missing_count=11,
        )

        with self.assertRaises(
            ECGQualityAssessmentError
        ):
            assess_ecg_processing_quality(
                signal
            )

    def test_invalid_layout_is_rejected(self):
        signal = self.create_reconstructed_signal()

        layout = self.create_lead_layout(
            row_count=0,
            cell_count=0,
        )

        with self.assertRaises(
            ECGQualityAssessmentError
        ):
            assess_ecg_processing_quality(
                signal,
                lead_layout=layout,
            )

    def test_invalid_grid_scale_is_rejected(self):
        signal = self.create_reconstructed_signal()

        grid_detection = (
            self.create_grid_detection(
                pixels_per_mm=0.0
            )
        )

        with self.assertRaises(
            ECGQualityAssessmentError
        ):
            assess_ecg_processing_quality(
                signal,
                grid_detection=grid_detection,
            )

    def test_high_quality_threshold_cannot_be_below_usable_threshold(
        self,
    ):
        signal = self.create_reconstructed_signal()

        with self.assertRaises(
            ECGQualityAssessmentError
        ):
            assess_ecg_processing_quality(
                signal,
                min_coverage_ratio=0.95,
                high_quality_coverage_ratio=0.90,
            )

    def test_custom_quality_thresholds_are_supported(self):
        signal = self.create_reconstructed_signal(
            coverage_ratio=0.85,
            sample_count=100,
            missing_count=15,
        )

        result = assess_ecg_processing_quality(
            signal,
            min_coverage_ratio=0.80,
            high_quality_coverage_ratio=0.95,
        )

        self.assertTrue(
            result.usable
        )

        self.assertEqual(
            result.quality_level,
            "acceptable",
        )