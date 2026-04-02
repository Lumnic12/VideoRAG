"""
setup.py — Windows-friendly pybind11 build for ssim_cpp.

Usage (from cpp_bindings/ directory):
    pip install pybind11 opencv-python-headless
    python setup.py build_ext --inplace

After build, copy the generated .pyd/.so into backend/services/:
    copy ssim_cpp*.pyd ..\backend\services\      # Windows
    cp ssim_cpp*.so ../backend/services/          # Linux/macOS

Requirements:
  - MSVC Build Tools (Windows) or GCC/Clang (Linux/macOS)
  - OpenCV installed with development headers
  - pybind11 (pip install pybind11)
"""
import os
import sys
import subprocess
from pathlib import Path
from setuptools import setup, Extension

# ── Locate pybind11 includes ──────────────────────────────────────────────────
try:
    import pybind11
    pybind11_include = pybind11.get_include()
except ImportError:
    print("ERROR: pybind11 not found. Run: pip install pybind11")
    sys.exit(1)

# ── Locate OpenCV includes + libs ─────────────────────────────────────────────
def get_opencv_flags():
    """Use pkg-config (Linux/macOS) or fallback hints (Windows)."""
    include_dirs = []
    library_dirs = []
    libraries = []
    extra_link_args = []

    # Try pkg-config first (Linux/macOS)
    try:
        cflags = subprocess.check_output(
            ["pkg-config", "--cflags", "opencv4"],
            stderr=subprocess.DEVNULL,
        ).decode().split()
        libs = subprocess.check_output(
            ["pkg-config", "--libs", "opencv4"],
            stderr=subprocess.DEVNULL,
        ).decode().split()
        for f in cflags:
            if f.startswith("-I"):
                include_dirs.append(f[2:])
        for l in libs:
            if l.startswith("-L"):
                library_dirs.append(l[2:])
            elif l.startswith("-l"):
                libraries.append(l[2:])
            else:
                extra_link_args.append(l)
        return include_dirs, library_dirs, libraries, extra_link_args
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Windows fallback — common OpenCV install paths
    win_hints = [
        Path("C:/opencv/build/include"),
        Path("C:/tools/opencv/build/include"),
        Path(os.environ.get("OPENCV_DIR", "C:/opencv/build") + "/include"),
    ]
    for hint in win_hints:
        if hint.exists():
            include_dirs.append(str(hint))
            lib_path = hint.parent / "x64" / "vc17" / "lib"
            if not lib_path.exists():
                lib_path = hint.parent / "x64" / "vc16" / "lib"
            if lib_path.exists():
                library_dirs.append(str(lib_path))
            break

    # On Windows pip install opencv-python-headless puts headers in site-packages
    try:
        import cv2
        cv2_path = Path(cv2.__file__).parent
        cv2_include = cv2_path / "include"
        if cv2_include.exists():
            include_dirs.append(str(cv2_include))
    except ImportError:
        pass

    # Common OpenCV libs (adjust version suffix as needed)
    if sys.platform == "win32":
        libraries = ["opencv_world490", "opencv_world4100"]  # try both
    else:
        libraries = ["opencv_core", "opencv_imgproc", "opencv_videoio"]

    return include_dirs, library_dirs, libraries, extra_link_args


cv_includes, cv_lib_dirs, cv_libs, cv_link_args = get_opencv_flags()

# ── Extension definition ──────────────────────────────────────────────────────
ext = Extension(
    name="ssim_cpp",
    sources=["ssim_extractor.cpp"],
    include_dirs=[pybind11_include] + cv_includes,
    library_dirs=cv_lib_dirs,
    libraries=cv_libs,
    extra_link_args=cv_link_args,
    extra_compile_args=(
        ["/O2", "/std:c++17"] if sys.platform == "win32"
        else ["-O3", "-std=c++17", "-fvisibility=hidden"]
    ),
    language="c++",
)

setup(
    name="ssim_cpp",
    version="1.0.0",
    description="C++ SSIM keyframe extractor for Semantic Video Synthesizer",
    ext_modules=[ext],
    zip_safe=False,
)
