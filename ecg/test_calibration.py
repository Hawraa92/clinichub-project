from django.test import SimpleTestCase

from ecg.services.calibration import (
    ECGCalibrationError,
    calibrate_reconstructed_signal,
)
from ecg.services.signal_reconstruction import (
    ReconstructedECGSignal,
)


class ECGCalibrationTests(SimpleTestCase):
    def make_signal(
        self,
        *,
        x_positions=(0, 10, 20),
        signal_values=(0.0, 10.0, -20.0),
    ):
        return ReconstructedECGSignal(
            width=len(x_positions),
            height=100,
            x_positions=tuple(
                x_positions
            ),
            y_positions=tuple(
                50.0
                for _ in x_positions
            ),
            signal_values=tuple(
                signal_values
            ),
            baseline_y=50.0,
            coverage_ratio=1.0,
            interpolated_columns=0,
            region_top=0,
            region_bottom=100,
        )

    def test_converts_pixel_space_to_seconds_and_millivolts(self):
        signal = self.make_signal()

        result = calibrate_reconstructed_signal(
            signal,
            pixels_per_mm=10.0,
            paper_speed_mm_per_s=25.0,
            gain_mm_per_mv=10.0,
        )

        self.assertEqual(
            result.time_seconds,
            (
                0.0,
                0.04,
                0.08,
            ),
        )

        self.assertEqual(
            result.amplitude_mv,
            (
                0.0,
                0.1,
                -0.2,
            ),
        )

        self.assertEqual(
            result.sample_count,
            3,
        )

        self.assertEqual(
            result.missing_count,
            0,
        )

        self.assertAlmostEqual(
            result.duration_seconds,
            0.08,
        )

    def test_missing_signal_values_are_preserved(self):
        signal = self.make_signal(
            signal_values=(
                0.0,
                None,
                10.0,
            ),
        )

        result = calibrate_reconstructed_signal(
            signal,
            pixels_per_mm=10.0,
        )

        self.assertEqual(
            result.amplitude_mv,
            (
                0.0,
                None,
                0.1,
            ),
        )

        self.assertEqual(
            result.sample_count,
            2,
        )

        self.assertEqual(
            result.missing_count,
            1,
        )

    def test_default_ecg_speed_and_gain_are_used(self):
        signal = self.make_signal()

        result = calibrate_reconstructed_signal(
            signal,
            pixels_per_mm=10.0,
        )

        self.assertEqual(
            result.parameters.paper_speed_mm_per_s,
            25.0,
        )

        self.assertEqual(
            result.parameters.gain_mm_per_mv,
            10.0,
        )

        self.assertEqual(
            result.parameters.pixels_per_mm,
            10.0,
        )

    def test_non_positive_pixels_per_mm_is_rejected(self):
        signal = self.make_signal()

        with self.assertRaises(
            ECGCalibrationError
        ):
            calibrate_reconstructed_signal(
                signal,
                pixels_per_mm=0,
            )

    def test_invalid_paper_speed_is_rejected(self):
        signal = self.make_signal()

        with self.assertRaises(
            ECGCalibrationError
        ):
            calibrate_reconstructed_signal(
                signal,
                pixels_per_mm=10.0,
                paper_speed_mm_per_s=-25.0,
            )

    def test_non_increasing_x_positions_are_rejected(self):
        signal = self.make_signal(
            x_positions=(
                0,
                10,
                10,
            ),
        )

        with self.assertRaises(
            ECGCalibrationError
        ):
            calibrate_reconstructed_signal(
                signal,
                pixels_per_mm=10.0,
            )

    def test_mismatched_signal_lengths_are_rejected(self):
        signal = self.make_signal(
            x_positions=(
                0,
                10,
                20,
            ),
            signal_values=(
                0.0,
                10.0,
            ),
        )

        with self.assertRaises(
            ECGCalibrationError
        ):
            calibrate_reconstructed_signal(
                signal,
                pixels_per_mm=10.0,
            )