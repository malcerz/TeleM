cmake_minimum_required(VERSION 3.15)
project(telem_nvenc_native VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

add_library(telem_nvenc_native SHARED
    src/telem_nvenc_native.cpp
    src/d3d11_nvenc_pipeline.cpp
    src/indicators/font_cache.cpp
    src/indicators/icon_cache.cpp
    src/indicators/text_indicator.cpp
    src/indicators/time_display_indicator.cpp
    src/indicators/bar_indicator.cpp
    src/indicators/segment_bar_indicator.cpp
    src/indicators/gauge_indicator.cpp
    src/indicators/chart_indicator.cpp
    src/indicators/map_indicator.cpp
)

target_compile_definitions(telem_nvenc_native PRIVATE TELEM_NVENC_BUILD_DLL)

target_include_directories(telem_nvenc_native PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/indicators
)

target_link_libraries(telem_nvenc_native PRIVATE
    d3d11
    dxgi
    d2d1
    dwrite
    mfplat
    mfreadwrite
    mfuuid
    ole32
    psapi
    windowscodecs
)

set_target_properties(telem_nvenc_native PROPERTIES
    PREFIX ""
    OUTPUT_NAME "telem_nvenc_native"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/lib"
)

if(MINGW)
    target_compile_options(telem_nvenc_native PRIVATE -Wall -Wextra -O3 -msse4.1)
    target_link_options(telem_nvenc_native PRIVATE
        -static-libgcc
        -static-libstdc++
        -Wl,-Bstatic -lwinpthread -Wl,-Bdynamic
    )
elseif(MSVC)
    target_compile_options(telem_nvenc_native PRIVATE /W4 /O2)
endif()
