/**
 * ssim_extractor.cpp
 * Phase 3 — C++ SSIM keyframe extractor with pybind11 bindings.
 *
 * Implements the same algorithm as frame_extractor.py but in C++ for
 * ~5x faster SSIM computation on long videos.
 *
 * Build:
 *   python setup.py build_ext --inplace         (Windows, no cmake needed)
 *   cmake .. && make -j4                         (Linux/macOS)
 *
 * Python usage after build:
 *   from ssim_cpp import extract_keyframes
 *   results = extract_keyframes("video.mp4", threshold=0.95)
 *   for r in results:
 *       print(r.index, r.timestamp_sec, r.ssim_delta)
 */
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <opencv2/opencv.hpp>
#include <vector>
#include <stdexcept>
#include <algorithm>
#include <string>

namespace py = pybind11;

// ── Data struct returned to Python ──────────────────────────────────────────

struct KeyframeResult {
    int index;
    double timestamp_sec;
    double ssim_delta;   ///< 1.0 - ssim_score; 0.0 for the first frame
};

// ── SSIM implementation ──────────────────────────────────────────────────────

/**
 * Compute mean SSIM between two single-channel (grayscale) images.
 * Uses Gaussian blur to estimate local statistics, matching skimage defaults.
 *
 * Args:
 *   img1, img2: CV_8U grayscale images (must be same size).
 * Returns:
 *   SSIM in [0, 1].
 */
double compute_ssim(const cv::Mat& img1, const cv::Mat& img2) {
    cv::Mat i1, i2;
    img1.convertTo(i1, CV_64F);
    img2.convertTo(i2, CV_64F);

    // SSIM constants — (k1*L)^2 and (k2*L)^2 with k1=0.01, k2=0.03, L=255
    const double C1 = 6.5025;   // (0.01 * 255)^2
    const double C2 = 58.5225;  // (0.03 * 255)^2
    const cv::Size ksize(11, 11);
    const double sigma = 1.5;

    cv::Mat mu1, mu2;
    cv::GaussianBlur(i1, mu1, ksize, sigma);
    cv::GaussianBlur(i2, mu2, ksize, sigma);

    cv::Mat mu1_sq  = mu1.mul(mu1);
    cv::Mat mu2_sq  = mu2.mul(mu2);
    cv::Mat mu1_mu2 = mu1.mul(mu2);

    cv::Mat sigma1_sq, sigma2_sq, sigma12;
    cv::GaussianBlur(i1.mul(i1), sigma1_sq, ksize, sigma); sigma1_sq -= mu1_sq;
    cv::GaussianBlur(i2.mul(i2), sigma2_sq, ksize, sigma); sigma2_sq -= mu2_sq;
    cv::GaussianBlur(i1.mul(i2), sigma12,   ksize, sigma); sigma12   -= mu1_mu2;

    cv::Mat num = (2.0 * mu1_mu2 + C1).mul(2.0 * sigma12 + C2);
    cv::Mat den = (mu1_sq + mu2_sq + C1).mul(sigma1_sq + sigma2_sq + C2);

    cv::Mat ssim_map;
    cv::divide(num, den, ssim_map);
    return cv::mean(ssim_map)[0];
}

// ── Core extraction loop ─────────────────────────────────────────────────────

/**
 * Extract semantic keyframes from a video using SSIM change detection.
 *
 * Matches the behaviour of backend/services/frame_extractor.py::extract_keyframes().
 * Returns only metadata (index, timestamp, delta) — actual frames are still
 * saved from Python to keep memory usage low on the C++ side.
 *
 * Args:
 *   video_path:    Path to .mp4/.mov/.avi file.
 *   threshold:     Frames with SSIM >= threshold are considered identical.
 *   min_interval:  Minimum seconds between consecutive keyframes.
 *   max_keyframes: Hard cap on number of keyframes returned.
 *   resize_width:  Width to downscale frames to before SSIM (speed optimisation).
 *
 * Raises:
 *   std::runtime_error if the video file cannot be opened.
 */
std::vector<KeyframeResult> extract_keyframes_cpp(
    const std::string& video_path,
    double threshold    = 0.95,
    double min_interval = 2.0,
    int    max_keyframes = 30,
    int    resize_width  = 640
) {
    cv::VideoCapture cap(video_path);
    if (!cap.isOpened()) {
        throw std::runtime_error("Cannot open video: " + video_path);
    }

    const double fps   = cap.get(cv::CAP_PROP_FPS);
    const int total    = static_cast<int>(cap.get(cv::CAP_PROP_FRAME_COUNT));
    // Sample at ~2 fps — same strategy as the Python implementation
    const int sample_interval = std::max(1, static_cast<int>(fps / 2.0));

    std::vector<KeyframeResult> results;
    cv::Mat frame, small, gray, prev_gray;

    for (int idx = 0; idx < total; idx += sample_interval) {
        cap.set(cv::CAP_PROP_POS_FRAMES, idx);
        if (!cap.read(frame)) break;

        // Downscale for faster SSIM
        double scale = static_cast<double>(resize_width) / frame.cols;
        cv::resize(frame, small,
                   cv::Size(resize_width, static_cast<int>(frame.rows * scale)));
        cv::cvtColor(small, gray, cv::COLOR_BGR2GRAY);

        if (prev_gray.empty()) {
            // First frame is always a keyframe
            results.push_back(KeyframeResult{
                static_cast<int>(results.size()),
                idx / fps,
                0.0
            });
            gray.copyTo(prev_gray);
            continue;
        }

        const double score     = compute_ssim(prev_gray, gray);
        const double timestamp = idx / fps;
        const double time_since_last = timestamp - results.back().timestamp_sec;

        if (score < threshold && time_since_last >= min_interval) {
            results.push_back(KeyframeResult{
                static_cast<int>(results.size()),
                timestamp,
                1.0 - score
            });
            gray.copyTo(prev_gray);

            if (static_cast<int>(results.size()) >= max_keyframes) break;
        }
    }

    cap.release();
    return results;
}

// ── pybind11 module ──────────────────────────────────────────────────────────

PYBIND11_MODULE(ssim_cpp, m) {
    m.doc() = "C++ SSIM keyframe extractor — Phase 3 of Semantic Video Synthesizer";

    py::class_<KeyframeResult>(m, "KeyframeResult",
        "Metadata for a detected keyframe (no raw image data).")
        .def_readonly("index",        &KeyframeResult::index,
                      "Zero-based keyframe index.")
        .def_readonly("timestamp_sec",&KeyframeResult::timestamp_sec,
                      "Timestamp in seconds from video start.")
        .def_readonly("ssim_delta",   &KeyframeResult::ssim_delta,
                      "1 - SSIM score vs previous keyframe (0 = first frame).");

    m.def("extract_keyframes", &extract_keyframes_cpp,
        py::arg("video_path"),
        py::arg("threshold")     = 0.95,
        py::arg("min_interval")  = 2.0,
        py::arg("max_keyframes") = 30,
        py::arg("resize_width")  = 640,
        R"doc(
Extract semantic keyframes from a video file.

Returns a list of KeyframeResult objects containing index, timestamp_sec,
and ssim_delta. Actual frame images must be saved from Python using OpenCV.

Args:
    video_path:    Path to video file (.mp4 / .mov / .avi / .mkv).
    threshold:     SSIM >= threshold → frames considered identical (default 0.95).
    min_interval:  Minimum seconds between keyframes (default 2.0).
    max_keyframes: Maximum number of keyframes to return (default 30).
    resize_width:  px width to resize frames before SSIM (default 640).

Raises:
    RuntimeError: If the video file cannot be opened.
        )doc"
    );
}
