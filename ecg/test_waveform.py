from django.test import SimpleTestCase

from ecg.services.parser import ParsedECG
from ecg.services.waveform import (
    ECGWaveformError,
    build_waveform_preview,
)


class ECGWaveformTests(SimpleTestCase):
    def test_waveform_uses_existing_time_axis(self):
        parsed_ecg = ParsedECG(
            source_format="csv",
            headers=(
                "time",
                "lead_I",
                "lead_II",
            ),
            signal_names=(
                "lead_I",
                "lead_II",
            ),
            signals={
                "lead_I": (
                    0.10,
                    0.15,
                    0.12,
                ),
                "lead_II": (
                    0.20,
                    0.25,
                    0.22,
                ),
            },
            row_count=3,
            time_values=(
                0.000,
                0.002,
                0.004,
            ),
            sampling_frequency_hz=500.0,
        )

        waveform = build_waveform_preview(
            parsed_ecg
        )

        self.assertEqual(
            waveform.x_values,
            (
                0.000,
                0.002,
                0.004,
            ),
        )

        self.assertEqual(
            waveform.x_unit,
            "seconds",
        )

        self.assertEqual(
            waveform.source_sample_count,
            3,
        )

        self.assertEqual(
            waveform.displayed_sample_count,
            3,
        )

        self.assertFalse(
            waveform.downsampled
        )

        self.assertEqual(
            len(waveform.leads),
            2,
        )

        self.assertEqual(
            waveform.leads[0].name,
            "lead_I",
        )

        self.assertEqual(
            waveform.leads[0].values,
            (
                0.10,
                0.15,
                0.12,
            ),
        )

    def test_waveform_builds_time_axis_from_sampling_frequency(self):
        parsed_ecg = ParsedECG(
            source_format="csv",
            headers=(
                "lead_I",
                "lead_II",
            ),
            signal_names=(
                "lead_I",
                "lead_II",
            ),
            signals={
                "lead_I": (
                    0.10,
                    0.15,
                    0.12,
                ),
                "lead_II": (
                    0.20,
                    0.25,
                    0.22,
                ),
            },
            row_count=3,
            time_values=None,
            sampling_frequency_hz=500.0,
        )

        waveform = build_waveform_preview(
            parsed_ecg
        )

        self.assertEqual(
            waveform.x_values,
            (
                0.0,
                0.002,
                0.004,
            ),
        )

        self.assertEqual(
            waveform.x_unit,
            "seconds",
        )

    def test_waveform_falls_back_to_sample_axis(self):
        parsed_ecg = ParsedECG(
            source_format="csv",
            headers=(
                "lead_I",
                "lead_II",
            ),
            signal_names=(
                "lead_I",
                "lead_II",
            ),
            signals={
                "lead_I": (
                    0.10,
                    0.15,
                    0.12,
                ),
                "lead_II": (
                    0.20,
                    0.25,
                    0.22,
                ),
            },
            row_count=3,
            time_values=None,
            sampling_frequency_hz=None,
        )

        waveform = build_waveform_preview(
            parsed_ecg
        )

        self.assertEqual(
            waveform.x_values,
            (
                0.0,
                1.0,
                2.0,
            ),
        )

        self.assertEqual(
            waveform.x_unit,
            "sample",
        )

    def test_waveform_preview_downsamples_for_display(self):
        values = tuple(
            float(index)
            for index in range(100)
        )

        parsed_ecg = ParsedECG(
            source_format="csv",
            headers=(
                "time",
                "lead_I",
            ),
            signal_names=(
                "lead_I",
            ),
            signals={
                "lead_I": values,
            },
            row_count=100,
            time_values=tuple(
                index / 500.0
                for index in range(100)
            ),
            sampling_frequency_hz=500.0,
        )

        waveform = build_waveform_preview(
            parsed_ecg,
            max_points=10,
        )

        self.assertEqual(
            waveform.source_sample_count,
            100,
        )

        self.assertEqual(
            waveform.displayed_sample_count,
            10,
        )

        self.assertTrue(
            waveform.downsampled
        )

        self.assertEqual(
            waveform.leads[0].values[0],
            0.0,
        )

        self.assertEqual(
            waveform.leads[0].values[-1],
            99.0,
        )

        self.assertEqual(
            waveform.x_values[0],
            0.0,
        )

        self.assertAlmostEqual(
            waveform.x_values[-1],
            99 / 500.0,
        )

    def test_waveform_rejects_inconsistent_signal_length(self):
        parsed_ecg = ParsedECG(
            source_format="csv",
            headers=(
                "time",
                "lead_I",
            ),
            signal_names=(
                "lead_I",
            ),
            signals={
                "lead_I": (
                    0.10,
                    0.15,
                ),
            },
            row_count=3,
            time_values=(
                0.000,
                0.002,
                0.004,
            ),
            sampling_frequency_hz=500.0,
        )

        with self.assertRaises(
            ECGWaveformError
        ):
            build_waveform_preview(
                parsed_ecg
            )

    def test_waveform_rejects_invalid_max_points(self):
        parsed_ecg = ParsedECG(
            source_format="csv",
            headers=(
                "time",
                "lead_I",
            ),
            signal_names=(
                "lead_I",
            ),
            signals={
                "lead_I": (
                    0.10,
                    0.15,
                ),
            },
            row_count=2,
            time_values=(
                0.000,
                0.002,
            ),
            sampling_frequency_hz=500.0,
        )

        with self.assertRaises(
            ECGWaveformError
        ):
            build_waveform_preview(
                parsed_ecg,
                max_points=1,
            )