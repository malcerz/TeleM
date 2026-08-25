cmake_minimum_required(VERSION 3.15)
project(telem_amd_native VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

find_package(Git QUIET)
set(TELEM_GIT_COMMIT "unknown")
set(TELEM_GIT_COMMIT_SHORT "unknown")
set(TELEM_BUILD_TIMESTAMP "unknown")
if(GIT_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE TELEM_GIT_COMMIT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse --short=12 HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE TELEM_GIT_COMMIT_SHORT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    execute_process(
        COMMAND ${GIT_EXECUTABLE} show -s --format=%cI HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE TELEM_BUILD_TIMESTAMP
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
endif()
if(NOT TELEM_BUILD_TIMESTAMP OR TELEM_BUILD_TIMESTAMP STREQUAL "unknown")
    string(TIMESTAMP TELEM_BUILD_TIMESTAMP "%Y-%m-%dT%H:%M:%SZ" UTC)
endif()

# Identify the exact production sources as well as the enclosing Git commit.  This
# remains stable across clean builds, including builds made from a dirty tree.
set(TELEM_BUILD_INPUTS
    CMakeLists.txt
    src/telem_amd_native.cpp
    src/d3d11_vp_pipeline.cpp
    src/d3d11_vp_pipeline.h
    src/d3d11_amf_encoder.cpp
    src/d3d11_amf_encoder.h
    src/telem_amd_build_info.h.in
)
set(TELEM_SOURCE_HASH_MATERIAL "")
foreach(input IN LISTS TELEM_BUILD_INPUTS)
    file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/${input}" input_hash)
    string(APPEND TELEM_SOURCE_HASH_MATERIAL "${input}:${input_hash}\n")
endforeach()
string(SHA256 TELEM_SOURCE_HASH "${TELEM_SOURCE_HASH_MATERIAL}")
string(SUBSTRING "${TELEM_SOURCE_HASH}" 0 12 TELEM_SOURCE_HASH_SHORT)
set(TELEM_BUILD_ID "telem-amd-native/${PROJECT_VERSION}+${TELEM_GIT_COMMIT_SHORT}.src${TELEM_SOURCE_HASH_SHORT}")
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/src/telem_amd_build_info.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/telem_amd_build_info.h
    @ONLY
)

add_library(telem_amd_native SHARED
    src/telem_amd_native.cpp
    src/d3d11_vp_pipeline.cpp
    src/d3d11_amf_encoder.cpp
)

target_include_directories(telem_amd_native PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_BINARY_DIR}/generated
)

target_link_libraries(telem_amd_native PRIVATE
    d3d11
    dxgi
    d3dcompiler
    mfplat
    mfreadwrite
    mfuuid
    ole32
)

set_target_properties(telem_amd_native PROPERTIES
    PREFIX ""
    OUTPUT_NAME "telem_amd_native"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/lib"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(telem_amd_native PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_${config} "${CMAKE_CURRENT_SOURCE_DIR}/bin"
        LIBRARY_OUTPUT_DIRECTORY_${config} "${CMAKE_CURRENT_SOURCE_DIR}/bin"
        ARCHIVE_OUTPUT_DIRECTORY_${config} "${CMAKE_CURRENT_BINARY_DIR}/lib"
    )
endforeach()

if(MINGW)
    target_compile_options(telem_amd_native PRIVATE -Wall -Wextra -O2)
    target_link_options(telem_amd_native PRIVATE
        -static-libgcc
        -static-libstdc++
        -Wl,--no-insert-timestamp
    )
elseif(MSVC)
    target_compile_options(telem_amd_native PRIVATE /W4 /O2)
endif()

add_executable(d3d11_etap2c_poc
    src/main_etap2c.cpp
    src/d3d11_vp_pipeline.cpp
    src/d3d11_vp_pipeline.h
    src/d3d11_amf_encoder.cpp
    src/d3d11_amf_encoder.h
)

target_link_libraries(d3d11_etap2c_poc PRIVATE
    d3d11.lib
    dxgi.lib
    d3dcompiler.lib
)

if(MSVC)
    target_compile_options(d3d11_etap2c_poc PRIVATE /W4 /O2)
endif()
