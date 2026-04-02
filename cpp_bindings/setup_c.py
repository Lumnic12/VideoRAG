"""
setup_c.py — Build ssim_fast.c as a Python C extension.

This version uses ONLY the Python C API (no OpenCV, no pybind11, no numpy headers).
It compiles on any platform where Python headers are available.

Usage:
    python cpp_bindings/setup_c.py build_ext --inplace
    copy cpp_bindings\\ssim_fast*.pyd backend\\services\\

Or run the helper script:
    cpp_bindings\\build_c.ps1
"""
from setuptools import setup, Extension
import sysconfig, sys

extra_compile = []
extra_link = []

if sys.platform == "win32":
    extra_compile = ["/O2", "/W3"]   # MSVC optimised
else:
    extra_compile = ["-O3", "-march=native", "-ffast-math"]

ssim_ext = Extension(
    name="ssim_fast",
    sources=["ssim_fast.c"],
    extra_compile_args=extra_compile,
    extra_link_args=extra_link,
    language="c",
)

setup(
    name="ssim_fast",
    version="1.0.0",
    description="Fast pure-C SSIM for VideoRAG Phase 3",
    ext_modules=[ssim_ext],
    zip_safe=False,
)
