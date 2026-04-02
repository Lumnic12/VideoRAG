cmake_minimum_required(VERSION 3.16)
project(ssim_cpp CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── pybind11 ──────────────────────────────────────────────────────────────────
# Locate via `python -m pybind11 --cmakedir` output.
# Pass with: cmake .. -Dpybind11_DIR=$(python -m pybind11 --cmakedir)
find_package(pybind11 REQUIRED)

# ── OpenCV ────────────────────────────────────────────────────────────────────
# Windows hint: set OpenCV_DIR to your OpenCV cmake config folder, e.g.
#   cmake .. -DOpenCV_DIR="C:/opencv/build"
find_package(OpenCV REQUIRED COMPONENTS core imgproc videoio)

# ── Build the Python extension ────────────────────────────────────────────────
pybind11_add_module(ssim_cpp ssim_extractor.cpp)
target_link_libraries(ssim_cpp PRIVATE ${OpenCV_LIBS})

# Output the .pyd/.so directly into backend/services for easy import
set_target_properties(ssim_cpp PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../backend/services"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../backend/services"
)

message(STATUS "OpenCV version : ${OpenCV_VERSION}")
message(STATUS "pybind11 version: ${pybind11_VERSION}")
message(STATUS "Output dir      : ${CMAKE_SOURCE_DIR}/../backend/services")
